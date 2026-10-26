from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, func, select

from src.analysis_runtime.domain.contracts import Activity, ActivityEvent
from src.analysis_runtime.infrastructure.sql_repository import (
    SqlAlchemyActivityRepository,
)
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
    WorkflowActivityCursor,
    WorkflowActivityEvent,
    WorkflowRun,
    WorkflowRunHistory,
)

pytestmark = pytest.mark.skipif(
    os.getenv("ANALYSIS_RUNTIME_POSTGRES_TEST") != "1",
    reason="requires the isolated PostgreSQL integration project",
)


@pytest.mark.asyncio
async def test_legacy_history_backfill_is_truthful_and_exact_runs_survive_restart() -> (
    None
):
    await init_db()
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

    repository = SqlAlchemyActivityRepository()
    thread_id = f"history-{uuid.uuid4()}"
    old_run_id = "legacy-complete"
    unknown_run_id = "legacy-unknown"
    current_run_id = "current-run"
    owner_id = str(uuid.uuid4())
    base_time = datetime.now(timezone.utc).replace(microsecond=0)
    try:
        async with AsyncSessionLocal() as session:
            session.add(
                UserModel(
                    id=owner_id,
                    email=f"{owner_id}@example.test",
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
                    run_id=current_run_id,
                    status="running",
                    started_at=(base_time + timedelta(seconds=10)).replace(tzinfo=None),
                    updated_at=(base_time + timedelta(seconds=11)).replace(tzinfo=None),
                    ended_at=None,
                )
            )
            session.add_all(
                [
                    WorkflowActivityEvent(
                        event_id=str(uuid.uuid4()),
                        thread_id=thread_id,
                        run_id=old_run_id,
                        seq_id=1,
                        event_version="v1",
                        event_name="workflow.activity",
                        occurred_at=base_time.replace(tzinfo=None),
                        payload={
                            "activity_id": "workflow",
                            "thread_id": thread_id,
                            "run_id": old_run_id,
                            "scope_path": ["workflow"],
                            "kind": "phase",
                            "status": "completed",
                            "label": "Workflow completed",
                            "attempt": 1,
                        },
                    ),
                    WorkflowActivityEvent(
                        event_id=str(uuid.uuid4()),
                        thread_id=thread_id,
                        run_id=unknown_run_id,
                        seq_id=3,
                        event_version="v1",
                        event_name="workflow.activity",
                        occurred_at=(base_time + timedelta(seconds=5)).replace(
                            tzinfo=None
                        ),
                        payload={
                            "activity_id": "analysis",
                            "thread_id": thread_id,
                            "run_id": unknown_run_id,
                            "scope_path": ["fundamental_analysis"],
                            "kind": "phase",
                            "status": "running",
                            "label": "Fundamental analysis",
                            "attempt": 1,
                        },
                    ),
                    WorkflowActivityEvent(
                        event_id=str(uuid.uuid4()),
                        thread_id=thread_id,
                        run_id=current_run_id,
                        seq_id=2,
                        event_version="v1",
                        event_name="workflow.activity",
                        occurred_at=(base_time + timedelta(seconds=11)).replace(
                            tzinfo=None
                        ),
                        payload={
                            "activity_id": "analysis",
                            "thread_id": thread_id,
                            "run_id": current_run_id,
                            "scope_path": ["fundamental_analysis"],
                            "kind": "phase",
                            "status": "running",
                            "label": "Fundamental analysis",
                            "attempt": 1,
                        },
                    ),
                ]
            )
            session.add(
                WorkflowActivityCursor(
                    thread_id=thread_id,
                    last_seq_id=3,
                    updated_at=(base_time + timedelta(seconds=11)).replace(tzinfo=None),
                )
            )
            await session.commit()

        await init_db()
        assert (
            await repository.get_run_history(
                principal_id=owner_id, thread_id=thread_id, run_id=old_run_id
            )
            is None
        )

        partial = await run_history_migration(batch_size=1, max_batches=1)
        assert partial.completed is False
        assert partial.batches_processed == 1
        async with AsyncSessionLocal() as session:
            remaining = await session.scalar(
                select(func.count())
                .select_from(DatabaseMigrationWorkItem)
                .where(DatabaseMigrationWorkItem.migration_id == HISTORY_MIGRATION_ID)
            )
        assert remaining is not None and remaining > 0

        completed = await asyncio.gather(
            run_history_migration(batch_size=1),
            run_history_migration(batch_size=1),
        )
        assert all(result.completed for result in completed)
        await assert_migrations_complete()
        await init_db()

        old_run = await repository.get_run_history(
            principal_id=owner_id, thread_id=thread_id, run_id=old_run_id
        )
        assert old_run is not None
        assert old_run.status == "completed"
        assert old_run.started_at is None
        assert old_run.input_data is None
        unknown_run = await repository.get_run_history(
            principal_id=owner_id, thread_id=thread_id, run_id=unknown_run_id
        )
        assert unknown_run is not None
        assert unknown_run.status == "unknown"
        assert unknown_run.started_at is None
        assert (
            await repository.get_run_history(
                principal_id="another-user", thread_id=thread_id, run_id=old_run_id
            )
            is None
        )
        first_page = await repository.list_run_history(principal_id=owner_id, limit=1)
        assert [record.run_id for record in first_page.runs] == [current_run_id]
        assert first_page.has_more
        second_page = await repository.list_run_history(
            principal_id=owner_id,
            limit=1,
            before_started_at=first_page.next_started_at,
            before_thread_id=first_page.next_thread_id,
            before_run_id=first_page.next_run_id,
        )
        assert [record.run_id for record in second_page.runs] == [unknown_run_id]
        assert second_page.runs[0].started_at is None
        assert second_page.has_more
        third_page = await repository.list_run_history(
            principal_id=owner_id,
            limit=1,
            before_started_at=second_page.next_started_at,
            before_thread_id=second_page.next_thread_id,
            before_run_id=second_page.next_run_id,
        )
        assert [record.run_id for record in third_page.runs] == [old_run_id]
        assert third_page.runs[0].status == "completed"
        assert third_page.has_more is False

        new_run_id = "runtime-created-run"
        await repository.set_run(
            thread_id=thread_id,
            run_id=new_run_id,
            status="queued",
            now=base_time + timedelta(seconds=20),
            principal_id=owner_id,
            input_data={"message": "AMZN"},
        )
        completed_at = base_time + timedelta(seconds=21)
        completion = Activity(
            activity_id="workflow",
            thread_id=thread_id,
            run_id=new_run_id,
            scope_path=("workflow",),
            kind="phase",
            status="completed",
            label="Workflow completed",
            attempt=1,
        )
        await repository.append_atomic(
            ActivityEvent(
                event_id=str(uuid.uuid4()),
                seq_id=4,
                thread_id=thread_id,
                run_id=new_run_id,
                occurred_at=completed_at,
                payload=completion,
            ),
            run_status="completed",
        )
        snapshot = await SqlAlchemyActivityRepository().snapshot(
            thread_id=thread_id, run_id=new_run_id
        )
        assert snapshot.run_status == "completed"
        assert [item.activity_id for item in snapshot.recent_activities] == ["workflow"]
        persisted_new_run = await SqlAlchemyActivityRepository().get_run_history(
            principal_id=owner_id, thread_id=thread_id, run_id=new_run_id
        )
        assert persisted_new_run is not None
        assert persisted_new_run.status == "completed"
        assert persisted_new_run.input_data == {"message": "AMZN"}
        persisted_old_run = await repository.get_run_history(
            principal_id=owner_id, thread_id=thread_id, run_id=old_run_id
        )
        assert persisted_old_run is not None
        assert persisted_old_run.status == "completed"
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(WorkflowRunHistory).where(
                    WorkflowRunHistory.thread_id == thread_id
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
                delete(WorkflowRun).where(WorkflowRun.thread_id == thread_id)
            )
            await session.execute(
                delete(OwnedResourceModel).where(
                    OwnedResourceModel.resource_id == thread_id
                )
            )
            await session.execute(delete(UserModel).where(UserModel.id == owner_id))
            await session.commit()
