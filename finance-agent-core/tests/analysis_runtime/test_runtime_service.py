from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from src.analysis_runtime.application.runtime_service import AnalysisRuntimeService
from src.analysis_runtime.domain.contracts import Activity, ActivityEvent
from src.analysis_runtime.domain.errors import (
    ActivityPersistenceError,
    ReplayGapError,
    ThreadNotFoundError,
)
from src.analysis_runtime.infrastructure.memory_repository import (
    InMemoryActivityRepository,
)
from src.analysis_runtime.infrastructure.notifications import BoundedNotificationHub


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


class FailingRepository(InMemoryActivityRepository):
    async def append_atomic(self, event):
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
    subscriber = await service.hub.subscribe()
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
    subscriber = await hub.subscribe()
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
