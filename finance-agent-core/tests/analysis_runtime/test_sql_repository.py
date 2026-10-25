from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete

from src.analysis_runtime.domain.contracts import (
    Activity,
    ActivityEvent,
    ActivityInterruption,
    TickerCandidate,
    TickerSelectionRequest,
    TickerSelectionResponse,
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
        interruption=ActivityInterruption(
            interaction_id=interaction_id,
            request=TickerSelectionRequest(
                type="ticker_selection",
                title="Ticker Resolution",
                description="Choose a company.",
                candidates=[
                    TickerCandidate(
                        symbol="GOOG", name="Alphabet Inc.", confidence=0.91
                    )
                ],
            ),
        ),
    )

    await repository.set_run(
        thread_id=thread_id, run_id=run_id, status="waiting", now=now
    )
    await repository.append_atomic(
        ActivityEvent(
            event_id=str(uuid.uuid4()),
            seq_id=1,
            thread_id=thread_id,
            run_id=run_id,
            occurred_at=now,
            payload=waiting,
        )
    )

    try:
        with pytest.raises(InvalidInteractionResponseError):
            await repository.claim_resume(
                thread_id=thread_id,
                run_id=run_id,
                activity_id=activity_id,
                interaction_id=interaction_id,
                response=TickerSelectionResponse(
                    type="ticker_selection", selected_symbol="MSFT"
                ),
                principal_id="user-1",
                now=now,
            )
        assert (await repository.get_run(thread_id=thread_id)).status == "waiting"

        async def claim():
            try:
                return await repository.claim_resume(
                    thread_id=thread_id,
                    run_id=run_id,
                    activity_id=activity_id,
                    interaction_id=interaction_id,
                    response=TickerSelectionResponse(
                        type="ticker_selection", selected_symbol="GOOG"
                    ),
                    principal_id="user-1",
                    now=now,
                )
            except InteractionNotAvailableError as error:
                return error

        results = await asyncio.gather(claim(), claim())
        assert sum(isinstance(result, Activity) for result in results) == 1
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
            await session.commit()
