from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete

from src.analysis_runtime.domain.contracts import (
    Activity,
    InteractionIdentity,
    InteractionRequested,
    TickerCandidate,
    TickerSelectionRequest,
    TickerSelectionResponse,
    WorkflowInteractionEvent,
)
from src.analysis_runtime.domain.errors import (
    InteractionNotAvailableError,
    InvalidInteractionResponseError,
)
from src.analysis_runtime.infrastructure.sql_repository import (
    SqlAlchemyActivityRepository,
)
from src.infrastructure.database import AsyncSessionLocal, init_db
from src.infrastructure.models import (
    WorkflowActivityCursor,
    WorkflowActivityEvent,
    WorkflowRun,
    WorkflowRunHistory,
    WorkflowRunResume,
)

pytestmark = pytest.mark.skipif(
    os.getenv("ANALYSIS_RUNTIME_POSTGRES_TEST") != "1",
    reason="requires the isolated PostgreSQL integration project",
)


@pytest.mark.asyncio
async def test_sql_resume_claim_is_atomic_and_validates_candidate() -> None:
    await init_db()
    thread_id = f"resume-test-{uuid.uuid4()}"
    run_id = str(uuid.uuid4())
    activity_id = "intent.clarifying"
    interaction_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    repository = SqlAlchemyActivityRepository()
    waiting = Activity(
        activity_id=activity_id,
        thread_id=thread_id,
        run_id=run_id,
        scope_path=("intent_extraction", "clarifying"),
        kind="node",
        status="waiting",
        label="Resolve ticker ambiguity",
        attempt=1,
    )

    identity = InteractionIdentity(
        thread_id=thread_id,
        run_id=run_id,
        activity_id=activity_id,
        interaction_id=interaction_id,
    )
    requested = InteractionRequested(
        activity=waiting,
        identity=identity,
        request=TickerSelectionRequest(
            type="ticker_selection",
            title="Ticker Resolution",
            description="Choose a company.",
            candidates=[
                TickerCandidate(symbol="GOOG", name="Alphabet Inc.", confidence=0.91)
            ],
        ),
    )
    await repository.set_run(
        thread_id=thread_id,
        run_id=run_id,
        status="running",
        now=now,
        principal_id="user-1",
    )
    with pytest.raises(InteractionNotAvailableError):
        await repository.record_waiting_interaction(
            requested=requested, principal_id="user-2", now=now
        )
    assert (await repository.get_run(thread_id=thread_id)).status == "running"
    await repository.record_waiting_interaction(
        requested=requested, principal_id="user-1", now=now
    )

    try:
        with pytest.raises(InteractionNotAvailableError):
            await repository.claim_interaction_response(
                identity=identity,
                response=TickerSelectionResponse(
                    type="ticker_selection", selected_symbol="GOOG"
                ),
                principal_id="user-2",
                now=now,
            )
        assert (await repository.get_run(thread_id=thread_id)).status == "waiting"

        with pytest.raises(InvalidInteractionResponseError):
            await repository.claim_interaction_response(
                identity=identity,
                response=TickerSelectionResponse(
                    type="ticker_selection", selected_symbol="MSFT"
                ),
                principal_id="user-1",
                now=now,
            )
        assert (await repository.get_run(thread_id=thread_id)).status == "waiting"

        async def claim():
            try:
                return await repository.claim_interaction_response(
                    identity=identity,
                    response=TickerSelectionResponse(
                        type="ticker_selection", selected_symbol="GOOG"
                    ),
                    principal_id="user-1",
                    now=now,
                )
            except InteractionNotAvailableError as error:
                return error

        results = await asyncio.gather(claim(), claim())
        assert (
            sum(
                not isinstance(result, InteractionNotAvailableError)
                for result in results
            )
            == 1
        )
        assert (
            sum(isinstance(result, InteractionNotAvailableError) for result in results)
            == 1
        )
        assert (await repository.get_run(thread_id=thread_id)).status == "running"
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(WorkflowActivityEvent).where(
                    WorkflowActivityEvent.thread_id == thread_id
                )
            )
            await session.execute(
                delete(WorkflowActivityCursor).where(
                    WorkflowActivityCursor.thread_id == thread_id
                )
            )
            await session.execute(
                delete(WorkflowRun).where(WorkflowRun.thread_id == thread_id)
            )
            await session.execute(
                delete(WorkflowRunResume).where(
                    WorkflowRunResume.thread_id == thread_id
                )
            )
            await session.execute(
                delete(WorkflowRunHistory).where(
                    WorkflowRunHistory.thread_id == thread_id
                )
            )
            await session.commit()


@pytest.mark.asyncio
async def test_sql_waiting_interaction_rolls_back_events_cursor_and_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await init_db()
    thread_id = f"interaction-rollback-{uuid.uuid4()}"
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    repository = SqlAlchemyActivityRepository()
    activity = Activity(
        activity_id="intent.clarifying",
        thread_id=thread_id,
        run_id=run_id,
        scope_path=("intent_extraction", "clarifying"),
        kind="node",
        status="waiting",
        label="Resolve ticker ambiguity",
        attempt=1,
    )
    requested = InteractionRequested(
        activity=activity,
        identity=InteractionIdentity(
            thread_id=thread_id,
            run_id=run_id,
            activity_id=activity.activity_id,
            interaction_id=str(uuid.uuid4()),
        ),
        request=TickerSelectionRequest(
            type="ticker_selection",
            title="Ticker Resolution",
            description="Choose a company.",
            candidates=[
                TickerCandidate(symbol="GOOG", name="Alphabet Inc.", confidence=0.91)
            ],
        ),
    )
    await repository.set_run(
        thread_id=thread_id,
        run_id=run_id,
        status="running",
        now=now,
        principal_id="user-1",
    )

    def fail_before_commit(_session, _cursor, _thread_id, _event, _now) -> None:
        raise RuntimeError("injected cursor persistence failure")

    monkeypatch.setattr(
        SqlAlchemyActivityRepository,
        "_advance_cursor",
        staticmethod(fail_before_commit),
    )

    try:
        with pytest.raises(RuntimeError, match="injected cursor persistence failure"):
            await repository.record_waiting_interaction(
                requested=requested, principal_id="user-1", now=now
            )

        run = await repository.get_run(thread_id=thread_id)
        history = await repository.get_run_history(
            principal_id="user-1", thread_id=thread_id, run_id=run_id
        )
        replay = await repository.replay(thread_id=thread_id, after_seq=0, limit=10)
        async with AsyncSessionLocal() as session:
            cursor = await session.get(WorkflowActivityCursor, thread_id)
        assert run is not None and run.status == "running"
        assert history is not None and history.status == "running"
        assert replay.events == ()
        assert cursor is None
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(WorkflowActivityEvent).where(
                    WorkflowActivityEvent.thread_id == thread_id
                )
            )
            await session.execute(
                delete(WorkflowActivityCursor).where(
                    WorkflowActivityCursor.thread_id == thread_id
                )
            )
            await session.execute(
                delete(WorkflowRunResume).where(
                    WorkflowRunResume.thread_id == thread_id
                )
            )
            await session.execute(
                delete(WorkflowRunHistory).where(
                    WorkflowRunHistory.thread_id == thread_id
                )
            )
            await session.execute(
                delete(WorkflowRun).where(WorkflowRun.thread_id == thread_id)
            )
            await session.commit()


@pytest.mark.asyncio
async def test_sql_response_and_cancel_race_preserves_one_consistent_lifecycle() -> (
    None
):
    await init_db()
    thread_id = f"interaction-cancel-race-{uuid.uuid4()}"
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    repository = SqlAlchemyActivityRepository()
    activity = Activity(
        activity_id="intent.clarifying",
        thread_id=thread_id,
        run_id=run_id,
        scope_path=("intent_extraction", "clarifying"),
        kind="node",
        status="waiting",
        label="Resolve ticker ambiguity",
        attempt=1,
    )
    identity = InteractionIdentity(
        thread_id=thread_id,
        run_id=run_id,
        activity_id=activity.activity_id,
        interaction_id=str(uuid.uuid4()),
    )
    requested = InteractionRequested(
        activity=activity,
        identity=identity,
        request=TickerSelectionRequest(
            type="ticker_selection",
            title="Ticker Resolution",
            description="Choose a company.",
            candidates=[
                TickerCandidate(symbol="GOOG", name="Alphabet Inc.", confidence=0.91)
            ],
        ),
    )
    await repository.set_run(
        thread_id=thread_id,
        run_id=run_id,
        status="running",
        now=now,
        principal_id="user-1",
    )
    await repository.record_waiting_interaction(
        requested=requested, principal_id="user-1", now=now
    )

    async def respond():
        return await repository.claim_interaction_response(
            identity=identity,
            response=TickerSelectionResponse(
                type="ticker_selection", selected_symbol="GOOG"
            ),
            principal_id="user-1",
            now=datetime.now(timezone.utc),
        )

    async def cancel():
        return await repository.cancel_run_with_interaction(
            thread_id=thread_id,
            run_id=run_id,
            principal_id="user-1",
            now=datetime.now(timezone.utc),
        )

    try:
        response_result, cancel_result = await asyncio.gather(
            respond(), cancel(), return_exceptions=True
        )
        assert isinstance(cancel_result, tuple) and cancel_result
        assert response_result is not None
        if isinstance(response_result, BaseException):
            assert isinstance(response_result, InteractionNotAvailableError)

        run = await repository.get_run(thread_id=thread_id)
        snapshot = await repository.snapshot(thread_id=thread_id, run_id=run_id)
        replay = await repository.replay(thread_id=thread_id, after_seq=0, limit=20)
        latest_interaction = next(
            event.payload
            for event in reversed(replay.events)
            if isinstance(event, WorkflowInteractionEvent)
        )
        assert run is not None and run.status == "cancelled"
        assert snapshot.run_status == "cancelled"
        assert snapshot.pending_interactions == ()
        assert latest_interaction.status in {"cancelled", "responded"}
        if latest_interaction.status == "responded":
            assert latest_interaction.response is not None
        else:
            assert latest_interaction.response is None
        assert await repository.pending_resumes() == ()
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(WorkflowActivityEvent).where(
                    WorkflowActivityEvent.thread_id == thread_id
                )
            )
            await session.execute(
                delete(WorkflowActivityCursor).where(
                    WorkflowActivityCursor.thread_id == thread_id
                )
            )
            await session.execute(
                delete(WorkflowRunResume).where(
                    WorkflowRunResume.thread_id == thread_id
                )
            )
            await session.execute(
                delete(WorkflowRunHistory).where(
                    WorkflowRunHistory.thread_id == thread_id
                )
            )
            await session.execute(
                delete(WorkflowRun).where(WorkflowRun.thread_id == thread_id)
            )
            await session.commit()
