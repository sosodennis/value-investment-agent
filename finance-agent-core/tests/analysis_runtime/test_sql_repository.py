from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete

from src.analysis_runtime.domain.contracts import (
    Activity,
    ActivityEvent,
    CheckpointIdentity,
    InteractionIdentity,
    InteractionRequested,
    TickerCandidate,
    TickerSelectionRequest,
    TickerSelectionResponse,
    ValuationApprovalRequest,
    ValuationApprovalResponse,
    WorkflowFailure,
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
    WorkflowRetryOperation,
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
async def test_sql_approval_response_is_versioned_and_restart_recoverable() -> None:
    await init_db()
    thread_id = f"approval-resume-test-{uuid.uuid4()}"
    run_id = str(uuid.uuid4())
    activity_id = "fundamental.calculation"
    now = datetime.now(timezone.utc)
    repository = SqlAlchemyActivityRepository()
    identity = InteractionIdentity(
        thread_id=thread_id,
        run_id=run_id,
        activity_id=activity_id,
        interaction_id=str(uuid.uuid4()),
    )
    requested = InteractionRequested(
        activity=Activity(
            activity_id=activity_id,
            thread_id=thread_id,
            run_id=run_id,
            scope_path=("fundamental_analysis", "calculation"),
            kind="node",
            status="waiting",
            label="Review valuation assumptions",
            attempt=1,
        ),
        identity=identity,
        request=ValuationApprovalRequest(
            type="valuation_approval",
            contract_version="v1",
            ticker="AAPL",
            model_type="dcf_growth",
            title="Review valuation assumptions",
            description="Approve before calculation.",
            parameters={"wacc": 0.09},
            audit_messages=["PASS: parameter set is valid"],
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

    response = ValuationApprovalResponse(
        type="valuation_approval", contract_version="v1", decision="reject"
    )
    try:
        with pytest.raises(InvalidInteractionResponseError):
            await repository.claim_interaction_response(
                identity=identity,
                response=TickerSelectionResponse(
                    type="ticker_selection", selected_symbol="AAPL"
                ),
                principal_id="user-1",
                now=now,
            )
        claimed = await repository.claim_interaction_response(
            identity=identity,
            response=response,
            principal_id="user-1",
            now=now,
        )
        assert claimed.response == response
        pending = await repository.pending_resumes()
        assert len(pending) == 1
        assert pending[0].identity == identity
        assert pending[0].response == response
        assert pending[0].response.decision == "reject"
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


@pytest.mark.asyncio
async def test_sql_retry_claim_converges_and_recovers_after_lease_expiry() -> None:
    await init_db()
    thread_id = f"retry-claim-{uuid.uuid4()}"
    source_run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).replace(microsecond=0)
    checkpoint = CheckpointIdentity(
        namespace="", checkpoint_id="checkpoint-1", activity_id="debate.verdict"
    )
    repository = SqlAlchemyActivityRepository()
    await repository.set_run(
        thread_id=thread_id,
        run_id=source_run_id,
        status="failed",
        now=now,
        principal_id="user-1",
    )
    failure_activity = Activity(
        activity_id="workflow",
        thread_id=thread_id,
        run_id=source_run_id,
        scope_path=("workflow",),
        kind="phase",
        status="failed",
        label="Workflow failed",
        attempt=1,
        failure=WorkflowFailure(
            code="rate_limited",
            owner="llm_provider",
            activity_id=checkpoint.activity_id,
            retryable=True,
            message="The provider temporarily rate limited this workflow.",
            checkpoint=checkpoint,
        ),
    )
    await repository.append_atomic(
        ActivityEvent(
            event_id=str(uuid.uuid4()),
            seq_id=1,
            thread_id=thread_id,
            run_id=source_run_id,
            occurred_at=now,
            payload=failure_activity,
        )
    )

    try:
        results = await asyncio.gather(
            repository.begin_retry(
                principal_id="user-1",
                thread_id=thread_id,
                source_run_id=source_run_id,
                checkpoint=checkpoint,
                idempotency_key="retry-key",
                request_hash="a" * 64,
                now=now,
            ),
            repository.begin_retry(
                principal_id="user-1",
                thread_id=thread_id,
                source_run_id=source_run_id,
                checkpoint=checkpoint,
                idempotency_key="retry-key",
                request_hash="a" * 64,
                now=now,
            ),
        )
        operation = results[0][0]
        assert results[1][0] == operation
        assert results[0][1] or results[1][1] is False

        claimed = await repository.claim_retry(
            operation_id=operation.operation_id,
            now=now,
            lease_seconds=300,
        )
        assert claimed is not None and claimed.status == "running"
        assert (
            await repository.claim_retry(
                operation_id=operation.operation_id,
                now=now + timedelta(seconds=1),
                lease_seconds=300,
            )
            is None
        )
        pending = await repository.pending_retries(
            now=now + timedelta(seconds=301), lease_seconds=300
        )
        assert [item.operation_id for item in pending] == [operation.operation_id]
        recovered = await repository.claim_retry(
            operation_id=operation.operation_id,
            now=now + timedelta(seconds=301),
            lease_seconds=300,
        )
        assert recovered is not None and recovered.status == "running"
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(WorkflowRetryOperation).where(
                    WorkflowRetryOperation.thread_id == thread_id
                )
            )
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
                delete(WorkflowRunHistory).where(
                    WorkflowRunHistory.thread_id == thread_id
                )
            )
            await session.execute(
                delete(WorkflowRun).where(WorkflowRun.thread_id == thread_id)
            )
            await session.commit()
