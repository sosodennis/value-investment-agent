from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, func, select

from src.auth.infrastructure.models import OwnedResourceModel, UserModel
from src.infrastructure.database import AsyncSessionLocal, init_db
from src.infrastructure.migrations import (
    HISTORY_MIGRATION_ID,
    assert_migrations_complete,
    run_history_migration,
)
from src.infrastructure.models import (
    DatabaseMigration,
    DatabaseMigrationWorkItem,
    WorkflowActivityEvent,
    WorkflowRun,
    WorkflowRunHistory,
)

pytestmark = pytest.mark.skipif(
    os.getenv("ANALYSIS_RUNTIME_POSTGRES_TEST") != "1",
    reason="requires the isolated PostgreSQL integration project",
)


async def _reset_migration_state() -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(DatabaseMigrationWorkItem).where(
                DatabaseMigrationWorkItem.migration_id == HISTORY_MIGRATION_ID
            )
        )
        await session.execute(
            delete(DatabaseMigration).where(
                DatabaseMigration.migration_id == HISTORY_MIGRATION_ID
            )
        )
        await session.commit()


def _event(
    *, thread_id: str, run_id: str, seq_id: int, status: str, occurred_at: datetime
) -> WorkflowActivityEvent:
    return WorkflowActivityEvent(
        event_id=str(uuid.uuid4()),
        thread_id=thread_id,
        run_id=run_id,
        seq_id=seq_id,
        event_version="v1",
        event_name="workflow.activity",
        occurred_at=occurred_at.replace(tzinfo=None),
        payload={
            "activity_id": "workflow"
            if status in {"completed", "failed"}
            else "analysis",
            "thread_id": thread_id,
            "run_id": run_id,
            "scope_path": ["workflow"],
            "kind": "phase",
            "status": status,
            "label": "Workflow activity",
            "attempt": 1,
        },
    )


@pytest.mark.asyncio
async def test_fresh_database_migration_completes_idempotently() -> None:
    await init_db()
    await _reset_migration_state()

    with pytest.raises(RuntimeError, match="migrations are pending"):
        await assert_migrations_complete()

    result = await run_history_migration(batch_size=2)
    assert result.completed
    assert result.batches_processed == 0
    await assert_migrations_complete()

    repeated = await run_history_migration(batch_size=2)
    assert repeated.completed
    assert repeated.batches_processed == 0


@pytest.mark.asyncio
async def test_legacy_backfill_is_bounded_resumable_and_concurrency_safe() -> None:
    await init_db()
    await _reset_migration_state()

    thread_id = f"history-{uuid.uuid4()}"
    unowned_thread_id = f"unowned-{uuid.uuid4()}"
    owner_id = str(uuid.uuid4())
    run_ids = [f"legacy-{index}" for index in range(5)]
    base_time = datetime.now(timezone.utc).replace(microsecond=0)

    async with AsyncSessionLocal() as session:
        session.add(
            UserModel(
                id=owner_id,
                email=f"{owner_id}@example.test",
                display_name="Migration Owner",
                display_name_normalized="migration owner",
                password_hash="test-only",
            )
        )
        await session.flush()
        session.add(
            OwnedResourceModel(
                resource_type="thread", resource_id=thread_id, user_id=owner_id
            )
        )
        session.add(
            WorkflowRun(
                thread_id=thread_id,
                run_id=run_ids[-1],
                status="running",
                started_at=(base_time + timedelta(seconds=8)).replace(tzinfo=None),
                updated_at=(base_time + timedelta(seconds=9)).replace(tzinfo=None),
                ended_at=None,
            )
        )
        session.add_all(
            [
                _event(
                    thread_id=thread_id,
                    run_id=run_ids[0],
                    seq_id=1,
                    status="completed",
                    occurred_at=base_time,
                ),
                _event(
                    thread_id=thread_id,
                    run_id=run_ids[1],
                    seq_id=2,
                    status="running",
                    occurred_at=base_time + timedelta(seconds=2),
                ),
                _event(
                    thread_id=thread_id,
                    run_id=run_ids[2],
                    seq_id=3,
                    status="failed",
                    occurred_at=base_time + timedelta(seconds=4),
                ),
                _event(
                    thread_id=thread_id,
                    run_id=run_ids[3],
                    seq_id=4,
                    status="running",
                    occurred_at=base_time + timedelta(seconds=6),
                ),
                _event(
                    thread_id=thread_id,
                    run_id=run_ids[-1],
                    seq_id=5,
                    status="running",
                    occurred_at=base_time + timedelta(seconds=9),
                ),
                _event(
                    thread_id=unowned_thread_id,
                    run_id="must-not-be-assigned",
                    seq_id=1,
                    status="completed",
                    occurred_at=base_time,
                ),
            ]
        )
        await session.commit()

    try:
        partial = await run_history_migration(batch_size=2, max_batches=1)
        assert partial.completed is False
        assert partial.batches_processed == 1
        async with AsyncSessionLocal() as session:
            migration = await session.get(DatabaseMigration, HISTORY_MIGRATION_ID)
            queued = await session.scalar(
                select(func.count())
                .select_from(DatabaseMigrationWorkItem)
                .where(DatabaseMigrationWorkItem.migration_id == HISTORY_MIGRATION_ID)
            )
            written = await session.scalar(
                select(func.count())
                .select_from(WorkflowRunHistory)
                .where(WorkflowRunHistory.thread_id == thread_id)
            )
        assert migration is not None
        assert migration.discovery_thread_id is not None
        assert migration.discovery_run_id is not None
        assert queued == 2
        assert written == 0

        results = await asyncio.gather(
            run_history_migration(batch_size=2),
            run_history_migration(batch_size=2),
        )
        assert all(result.completed for result in results)
        await assert_migrations_complete()

        async with AsyncSessionLocal() as session:
            records = (
                await session.scalars(
                    select(WorkflowRunHistory)
                    .where(WorkflowRunHistory.thread_id == thread_id)
                    .order_by(WorkflowRunHistory.run_id)
                )
            ).all()
            unowned = await session.scalar(
                select(func.count())
                .select_from(WorkflowRunHistory)
                .where(WorkflowRunHistory.thread_id == unowned_thread_id)
            )
        by_run_id = {record.run_id: record for record in records}
        assert set(by_run_id) == set(run_ids)
        assert unowned == 0
        assert by_run_id[run_ids[0]].status == "completed"
        assert by_run_id[run_ids[0]].started_at is None
        assert by_run_id[run_ids[0]].input_data is None
        assert by_run_id[run_ids[1]].status == "unknown"
        assert by_run_id[run_ids[1]].started_at is None
        assert by_run_id[run_ids[1]].ended_at is None
        assert by_run_id[run_ids[2]].status == "failed"
        assert by_run_id[run_ids[3]].status == "unknown"
        assert by_run_id[run_ids[-1]].status == "running"
        assert by_run_id[run_ids[-1]].started_at == (
            base_time + timedelta(seconds=8)
        ).replace(tzinfo=None)
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(WorkflowRunHistory).where(
                    WorkflowRunHistory.thread_id.in_([thread_id, unowned_thread_id])
                )
            )
            await session.execute(
                delete(WorkflowActivityEvent).where(
                    WorkflowActivityEvent.thread_id.in_([thread_id, unowned_thread_id])
                )
            )
            await session.execute(
                delete(WorkflowRun).where(WorkflowRun.thread_id == thread_id)
            )
            await session.execute(
                delete(OwnedResourceModel).where(
                    OwnedResourceModel.resource_id == thread_id
                )
            )
            await session.execute(delete(UserModel).where(UserModel.id == owner_id))
            await session.commit()
