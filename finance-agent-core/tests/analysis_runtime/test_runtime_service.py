from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from src.analysis_runtime.application.runtime_service import AnalysisRuntimeService
from src.analysis_runtime.domain.contracts import (
    Activity,
    ActivityEvent,
    ActivityInterruption,
    TickerCandidate,
    TickerSelectionRequest,
    TickerSelectionResponse,
)
from src.analysis_runtime.domain.errors import (
    ActivityPersistenceError,
    InteractionNotAvailableError,
    InvalidInteractionResponseError,
    ReplayGapError,
    ThreadNotFoundError,
)
from src.analysis_runtime.infrastructure.memory_repository import (
    InMemoryActivityRepository,
)
from src.analysis_runtime.infrastructure.notifications import BoundedNotificationHub


def activity_event(*, thread_id: str, seq_id: int, event_id: str) -> ActivityEvent:
    return ActivityEvent(
        event_id=event_id,
        seq_id=seq_id,
        thread_id=thread_id,
        run_id=f"run-{thread_id}",
        occurred_at=datetime.now(timezone.utc),
        payload=Activity(
            activity_id=f"workflow.{seq_id}",
            thread_id=thread_id,
            run_id=f"run-{thread_id}",
            scope_path=("workflow", str(seq_id)),
            kind="node",
            status="running",
            label="Workflow",
            attempt=1,
        ),
    )


class Owner:
    def __init__(self, owned: set[str] | None = None) -> None:
        self.owned = {"thread"} if owned is None else owned

    async def owns(self, *, principal_id: str, thread_id: str) -> bool:
        return thread_id in self.owned

    async def claim(self, *, principal_id: str, thread_id: str) -> bool:
        self.owned.add(thread_id)
        return True


class Runner:
    async def run(self, **kwargs):
        yield Activity(
            activity_id="intent.extraction",
            thread_id=kwargs["thread_id"],
            run_id=kwargs["run_id"],
            scope_path=("intent", "extraction"),
            kind="node",
            status="running",
            label="Resolve intent",
            attempt=1,
        )


class FailingRunner:
    async def run(self, **kwargs):
        raise RuntimeError("runner failed")
        yield  # pragma: no cover


class InterruptingRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        if "interrupt_response" not in kwargs["input_data"]:
            yield Activity(
                activity_id="intent.clarifying",
                thread_id=kwargs["thread_id"],
                run_id=kwargs["run_id"],
                scope_path=("intent_extraction", "clarifying"),
                kind="node",
                status="waiting",
                label="Ticker Resolution",
                attempt=1,
                interruption=ActivityInterruption(
                    interaction_id="interaction-1",
                    request=TickerSelectionRequest(
                        type="ticker_selection",
                        title="Ticker Resolution",
                        description="Choose a company.",
                        candidates=[
                            TickerCandidate(
                                symbol="AAPL", name="Apple Inc.", confidence=0.96
                            ),
                            TickerCandidate(
                                symbol="APLE", name="Apple Hospitality", confidence=0.83
                            ),
                        ],
                    ),
                ),
            )
            return

        yield Activity(
            activity_id=kwargs["input_data"]["resuming_activity_id"],
            thread_id=kwargs["thread_id"],
            run_id=kwargs["run_id"],
            scope_path=tuple(kwargs["input_data"]["resuming_scope_path"]),
            kind="node",
            status="running",
            label="Ticker Resolution",
            attempt=kwargs["input_data"]["resuming_attempt"] + 1,
        )


class FailingRepository(InMemoryActivityRepository):
    async def append_atomic(self, event, *, run_status=None):
        raise RuntimeError("storage unavailable")


@pytest.mark.asyncio
async def test_runtime_persists_before_publish_and_replays() -> None:
    repository = InMemoryActivityRepository()
    service = AnalysisRuntimeService(
        repository=repository,
        owner=Owner(),
        runner=Runner(),
        hub=BoundedNotificationHub(queue_size=4),
    )
    run_id = await service.start(
        principal_id="user",
        thread_id="thread",
        input_data={"message": "AAPL"},
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    replay = await service.replay(principal_id="user", thread_id="thread", after_seq=0)
    assert [event.seq_id for event in replay.events] == [1, 2]
    assert replay.events[-1].payload.status == "completed"
    snapshot = await service.snapshot(
        principal_id="user", thread_id="thread", run_id=run_id
    )
    assert snapshot.run_status == "completed"


@pytest.mark.asyncio
async def test_interrupt_waits_and_resumes_the_same_run_once() -> None:
    repository = InMemoryActivityRepository()
    runner = InterruptingRunner()
    service = AnalysisRuntimeService(
        repository=repository,
        owner=Owner(),
        runner=runner,
        hub=BoundedNotificationHub(queue_size=8),
    )
    run_id = await service.start(
        principal_id="user",
        thread_id="thread",
        input_data={"message": "Apple"},
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    waiting = await service.snapshot(
        principal_id="user", thread_id="thread", run_id=run_id
    )
    assert waiting.run_status == "waiting"
    assert [item.activity_id for item in waiting.active_activities] == [
        "intent.clarifying"
    ]
    assert waiting.active_activities[0].interruption is not None
    assert waiting.active_activities[0].interruption.request.type == "ticker_selection"
    before_resume = await service.replay(
        principal_id="user", thread_id="thread", after_seq=0
    )
    assert all(
        event.payload.activity_id != "workflow" for event in before_resume.events
    )

    with pytest.raises(InvalidInteractionResponseError):
        await service.resume(
            principal_id="user",
            thread_id="thread",
            run_id=run_id,
            activity_id="intent.clarifying",
            interaction_id="interaction-1",
            response=TickerSelectionResponse(
                type="ticker_selection", selected_symbol="MSFT"
            ),
        )
    assert (await repository.get_run(thread_id="thread")).status == "waiting"

    resumed_run_id = await service.resume(
        principal_id="user",
        thread_id="thread",
        run_id=run_id,
        activity_id="intent.clarifying",
        interaction_id="interaction-1",
        response=TickerSelectionResponse(
            type="ticker_selection", selected_symbol="AAPL"
        ),
    )
    assert resumed_run_id == run_id
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    after_resume = await service.replay(
        principal_id="user", thread_id="thread", after_seq=0
    )
    resumed_activity = next(
        event.payload
        for event in after_resume.events
        if event.payload.activity_id == "intent.clarifying"
        and event.payload.status == "running"
    )
    assert resumed_activity.attempt == 2
    assert (await repository.get_run(thread_id="thread")).status == "completed"
    assert runner.calls[1]["input_data"]["interrupt_response"] == {
        "type": "ticker_selection",
        "selected_symbol": "AAPL",
    }

    with pytest.raises(InteractionNotAvailableError):
        await service.resume(
            principal_id="user",
            thread_id="thread",
            run_id=run_id,
            activity_id="intent.clarifying",
            interaction_id="interaction-1",
            response=TickerSelectionResponse(
                type="ticker_selection", selected_symbol="AAPL"
            ),
        )


@pytest.mark.asyncio
async def test_claimed_resume_recovers_after_runtime_restart() -> None:
    repository = InMemoryActivityRepository()
    initial_runner = InterruptingRunner()
    service = AnalysisRuntimeService(
        repository=repository,
        owner=Owner(),
        runner=initial_runner,
    )
    run_id = await service.start(
        principal_id="user",
        thread_id="thread",
        input_data={"message": "Apple"},
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    waiting = await service.snapshot(
        principal_id="user", thread_id="thread", run_id=run_id
    )
    activity = waiting.active_activities[0]
    assert activity.interruption is not None

    await repository.claim_resume(
        thread_id="thread",
        run_id=run_id,
        activity_id=activity.activity_id,
        interaction_id=activity.interruption.interaction_id,
        response=TickerSelectionResponse(
            type="ticker_selection", selected_symbol="AAPL"
        ),
        principal_id="user",
        now=datetime.now(timezone.utc),
    )

    recovery_runner = InterruptingRunner()
    restarted_service = AnalysisRuntimeService(
        repository=repository,
        owner=Owner(),
        runner=recovery_runner,
    )
    assert await restarted_service.recover_pending_resumes() == 1
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert recovery_runner.calls[0]["input_data"]["interrupt_response"] == {
        "type": "ticker_selection",
        "selected_symbol": "AAPL",
    }
    assert (await repository.get_run(thread_id="thread")).status == "completed"
    assert await repository.pending_resumes() == ()


@pytest.mark.asyncio
async def test_owner_checked_before_replay() -> None:
    service = AnalysisRuntimeService(
        repository=InMemoryActivityRepository(), owner=Owner(set()), runner=Runner()
    )
    with pytest.raises(ThreadNotFoundError):
        await service.replay(principal_id="other", thread_id="thread", after_seq=0)


@pytest.mark.asyncio
async def test_replay_gap_is_typed() -> None:
    repository = InMemoryActivityRepository(replay_retention=1)
    owner = Owner()
    service = AnalysisRuntimeService(
        repository=repository, owner=owner, runner=Runner()
    )
    await service.start(
        principal_id="user", thread_id="thread", input_data={"message": "x"}
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    with pytest.raises(ReplayGapError):
        await service.replay(principal_id="user", thread_id="thread", after_seq=0)


@pytest.mark.asyncio
async def test_failed_run_publishes_terminal_activity() -> None:
    service = AnalysisRuntimeService(
        repository=InMemoryActivityRepository(), owner=Owner(), runner=FailingRunner()
    )
    run_id = await service.start(
        principal_id="user", thread_id="thread", input_data={"message": "x"}
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    replay = await service.replay(principal_id="user", thread_id="thread", after_seq=0)
    assert replay.events[-1].payload.status == "failed"
    assert replay.events[-1].run_id == run_id


@pytest.mark.asyncio
async def test_storage_failure_does_not_publish_unpersisted_event() -> None:
    repository = FailingRepository()
    service = AnalysisRuntimeService(
        repository=repository, owner=Owner(), runner=Runner()
    )
    subscriber = await service.hub.subscribe(thread_id="thread")
    with pytest.raises(ActivityPersistenceError):
        await service._persist_and_publish(
            # Exercise the persistence-before-publish boundary directly.
            ActivityEvent(
                event_id="evt",
                seq_id=1,
                thread_id="thread",
                run_id="run",
                occurred_at=datetime.now(timezone.utc),
                payload=Activity(
                    activity_id="workflow",
                    thread_id="thread",
                    run_id="run",
                    scope_path=("workflow",),
                    kind="phase",
                    status="running",
                    label="Workflow",
                    attempt=1,
                ),
            )
        )
    assert subscriber._queue.empty()


@pytest.mark.asyncio
async def test_slow_subscriber_is_bounded() -> None:
    hub = BoundedNotificationHub(queue_size=1)
    subscriber = await hub.subscribe(thread_id="thread")
    event = ActivityEvent(
        event_id="evt",
        seq_id=1,
        thread_id="thread",
        run_id="run",
        occurred_at=datetime.now(timezone.utc),
        payload=Activity(
            activity_id="workflow",
            thread_id="thread",
            run_id="run",
            scope_path=("workflow",),
            kind="phase",
            status="running",
            label="Workflow",
            attempt=1,
        ),
    )
    await hub.publish(event)
    await hub.publish(event.model_copy(update={"event_id": "evt-2", "seq_id": 2}))
    assert await subscriber.receive() is None


@pytest.mark.asyncio
async def test_subscribers_receive_only_their_thread_events() -> None:
    hub = BoundedNotificationHub(queue_size=4)
    first = await hub.subscribe(thread_id="thread-a")
    second = await hub.subscribe(thread_id="thread-b")
    event_a = activity_event(thread_id="thread-a", seq_id=1, event_id="a-1")
    event_b = activity_event(thread_id="thread-b", seq_id=1, event_id="b-1")
    await hub.publish(event_a)
    await hub.publish(event_b)
    assert await first.receive() == event_a
    assert await second.receive() == event_b
    assert first._queue.empty()
    assert second._queue.empty()


@pytest.mark.asyncio
async def test_retention_keeps_monotonic_cursor_after_eviction() -> None:
    repository = InMemoryActivityRepository(replay_retention=2)
    for seq_id in range(1, 5):
        assert await repository.append_atomic(
            activity_event(
                thread_id="thread-a", seq_id=seq_id, event_id=f"event-{seq_id}"
            )
        )
    with pytest.raises(ReplayGapError) as error:
        await repository.replay(thread_id="thread-a", after_seq=1, limit=10)
    assert error.value.oldest_seq == 3
    page = await repository.replay(thread_id="thread-a", after_seq=3, limit=10)
    assert page.cursor == 4
    assert [event.seq_id for event in page.events] == [4]
    assert await repository.append_atomic(
        activity_event(thread_id="thread-a", seq_id=5, event_id="event-5")
    )
    empty = await repository.replay(thread_id="thread-a", after_seq=5, limit=10)
    assert empty.cursor == 5
    future = await repository.replay(thread_id="thread-a", after_seq=99, limit=10)
    assert future.cursor == 99
