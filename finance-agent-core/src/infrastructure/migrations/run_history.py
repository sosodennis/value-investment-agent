from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import and_, case, delete, func, select, text, tuple_, union
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased

from src.auth.infrastructure.models import OwnedResourceModel
from src.infrastructure.database import AsyncSessionLocal
from src.infrastructure.models import (
    DatabaseMigration,
    DatabaseMigrationWorkItem,
    WorkflowActivityEvent,
    WorkflowRun,
    WorkflowRunHistory,
)

HISTORY_MIGRATION_ID = "20261025_workflow_run_history_v1"
RETRY_SCHEMA_MIGRATION_ID = "20261030_workflow_retry_schema_v1"
DEFAULT_BATCH_SIZE = 200
MAX_BATCH_SIZE = 500
_TERMINAL_STATUSES = ("completed", "failed", "cancelled")


@dataclass(frozen=True)
class MigrationResult:
    completed: bool
    batches_processed: int


async def run_retry_schema_migration() -> None:
    """Add retry columns/table without rewriting immutable run history."""
    statements = (
        "ALTER TABLE workflow_run_history ADD COLUMN IF NOT EXISTS source_run_id VARCHAR",
        "ALTER TABLE workflow_run_history ADD COLUMN IF NOT EXISTS retry_operation_id VARCHAR",
        "ALTER TABLE workflow_run_history ADD COLUMN IF NOT EXISTS attempt INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE workflow_run_history ADD COLUMN IF NOT EXISTS checkpoint JSON",
        "ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS dedupe_key VARCHAR",
        """
        CREATE TABLE IF NOT EXISTS workflow_retry_operations (
            operation_id VARCHAR PRIMARY KEY,
            thread_id VARCHAR NOT NULL,
            source_run_id VARCHAR NOT NULL,
            target_run_id VARCHAR NOT NULL UNIQUE,
            principal_id VARCHAR NOT NULL,
            idempotency_key VARCHAR NOT NULL,
            request_hash VARCHAR NOT NULL,
            checkpoint JSON NOT NULL,
            attempt INTEGER NOT NULL,
            status VARCHAR NOT NULL,
            outcome VARCHAR,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            ended_at TIMESTAMP
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_workflow_retry_principal_idempotency ON workflow_retry_operations (principal_id, idempotency_key)",
        "CREATE INDEX IF NOT EXISTS idx_workflow_retry_source ON workflow_retry_operations (thread_id, source_run_id)",
        "CREATE INDEX IF NOT EXISTS idx_workflow_run_history_retry_operation ON workflow_run_history (retry_operation_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_artifacts_dedupe_key ON artifacts (dedupe_key) WHERE dedupe_key IS NOT NULL",
    )
    async with AsyncSessionLocal() as session:
        async with session.begin():
            for statement in statements:
                await session.execute(text(statement))
            await session.execute(
                pg_insert(DatabaseMigration)
                .values(
                    migration_id=RETRY_SCHEMA_MIGRATION_ID,
                    initialized_at=_utcnow_naive(),
                    completed_at=_utcnow_naive(),
                )
                .on_conflict_do_update(
                    index_elements=["migration_id"],
                    set_={"completed_at": _utcnow_naive()},
                )
            )


async def run_history_migration(
    *, batch_size: int = DEFAULT_BATCH_SIZE, max_batches: int | None = None
) -> MigrationResult:
    if batch_size < 1 or batch_size > MAX_BATCH_SIZE:
        raise ValueError(f"batch_size must be between 1 and {MAX_BATCH_SIZE}")
    if max_batches is not None and max_batches < 1:
        raise ValueError("max_batches must be positive")

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                pg_insert(DatabaseMigration)
                .values(migration_id=HISTORY_MIGRATION_ID)
                .on_conflict_do_nothing(index_elements=["migration_id"])
            )

    batches_processed = 0
    while True:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                migration = await session.get(
                    DatabaseMigration,
                    HISTORY_MIGRATION_ID,
                    with_for_update=True,
                )
                if migration is None:
                    raise RuntimeError("history migration state was not initialized")
                if migration.completed_at is not None:
                    return MigrationResult(True, batches_processed)

                if migration.discovery_completed_at is None:
                    keys = await _next_owned_run_keys(session, migration, batch_size)
                    if keys:
                        await session.execute(
                            pg_insert(DatabaseMigrationWorkItem)
                            .values(
                                [
                                    {
                                        "migration_id": HISTORY_MIGRATION_ID,
                                        "thread_id": thread_id,
                                        "run_id": run_id,
                                    }
                                    for thread_id, run_id in keys
                                ]
                            )
                            .on_conflict_do_nothing(
                                index_elements=["migration_id", "thread_id", "run_id"]
                            )
                        )
                        migration.initialized_at = (
                            migration.initialized_at or _utcnow_naive()
                        )
                        migration.discovery_thread_id, migration.discovery_run_id = (
                            keys[-1]
                        )
                        batches_processed += 1
                    else:
                        migration.initialized_at = (
                            migration.initialized_at or _utcnow_naive()
                        )
                        migration.discovery_completed_at = _utcnow_naive()
                else:
                    work_items = (
                        await session.scalars(
                            select(DatabaseMigrationWorkItem)
                            .where(
                                DatabaseMigrationWorkItem.migration_id
                                == HISTORY_MIGRATION_ID
                            )
                            .order_by(
                                DatabaseMigrationWorkItem.thread_id,
                                DatabaseMigrationWorkItem.run_id,
                            )
                            .limit(batch_size)
                        )
                    ).all()
                    if not work_items:
                        migration.completed_at = _utcnow_naive()
                        return MigrationResult(True, batches_processed)

                    keys = [(item.thread_id, item.run_id) for item in work_items]
                    await _backfill_history_batch(session, work_items, keys)
                    await session.execute(
                        delete(DatabaseMigrationWorkItem).where(
                            DatabaseMigrationWorkItem.migration_id
                            == HISTORY_MIGRATION_ID,
                            tuple_(
                                DatabaseMigrationWorkItem.thread_id,
                                DatabaseMigrationWorkItem.run_id,
                            ).in_(keys),
                        )
                    )
                    batches_processed += 1

        if max_batches is not None and batches_processed >= max_batches:
            return MigrationResult(False, batches_processed)


async def assert_migrations_complete() -> None:
    async with AsyncSessionLocal() as session:
        migration = await session.get(DatabaseMigration, HISTORY_MIGRATION_ID)
    if migration is None or migration.completed_at is None:
        raise RuntimeError(
            "database migrations are pending; run "
            "python -m src.infrastructure.migrations.cli before starting the API"
        )


async def _next_owned_run_keys(
    session, migration: DatabaseMigration, batch_size: int
) -> list[tuple[str, str]]:
    event_keys = select(
        WorkflowActivityEvent.thread_id.label("thread_id"),
        WorkflowActivityEvent.run_id.label("run_id"),
    ).distinct()
    current_run_keys = select(
        WorkflowRun.thread_id.label("thread_id"),
        WorkflowRun.run_id.label("run_id"),
    )
    event_keys = event_keys.join(
        OwnedResourceModel,
        and_(
            OwnedResourceModel.resource_type == "thread",
            OwnedResourceModel.resource_id == WorkflowActivityEvent.thread_id,
        ),
    )
    current_run_keys = current_run_keys.join(
        OwnedResourceModel,
        and_(
            OwnedResourceModel.resource_type == "thread",
            OwnedResourceModel.resource_id == WorkflowRun.thread_id,
        ),
    )
    if migration.discovery_thread_id is not None:
        cursor = tuple_(migration.discovery_thread_id, migration.discovery_run_id)
        event_keys = event_keys.where(
            tuple_(WorkflowActivityEvent.thread_id, WorkflowActivityEvent.run_id)
            > cursor
        )
        current_run_keys = current_run_keys.where(
            tuple_(WorkflowRun.thread_id, WorkflowRun.run_id) > cursor
        )
    event_keys = event_keys.order_by(
        WorkflowActivityEvent.thread_id, WorkflowActivityEvent.run_id
    ).limit(batch_size)
    current_run_keys = current_run_keys.order_by(
        WorkflowRun.thread_id, WorkflowRun.run_id
    ).limit(batch_size)
    owned_keys = union(event_keys, current_run_keys).subquery()
    statement = select(owned_keys.c.thread_id, owned_keys.c.run_id)
    rows = (
        await session.execute(
            statement.order_by(owned_keys.c.thread_id, owned_keys.c.run_id).limit(
                batch_size
            )
        )
    ).all()
    return [(row[0], row[1]) for row in rows]


async def _backfill_history_batch(session, work_items, keys) -> None:
    thread_ids = {item.thread_id for item in work_items}
    owners = (
        await session.execute(
            select(OwnedResourceModel.resource_id, OwnedResourceModel.user_id).where(
                OwnedResourceModel.resource_type == "thread",
                OwnedResourceModel.resource_id.in_(thread_ids),
            )
        )
    ).all()
    principal_by_thread = dict(owners)

    run_rows = (
        await session.scalars(
            select(WorkflowRun).where(
                tuple_(WorkflowRun.thread_id, WorkflowRun.run_id).in_(keys)
            )
        )
    ).all()
    run_by_key = {(row.thread_id, row.run_id): row for row in run_rows}

    event_summary = (
        select(
            WorkflowActivityEvent.thread_id.label("thread_id"),
            WorkflowActivityEvent.run_id.label("run_id"),
            func.max(WorkflowActivityEvent.seq_id).label("latest_seq_id"),
            func.max(
                case(
                    (
                        and_(
                            WorkflowActivityEvent.payload["activity_id"].as_string()
                            == "workflow",
                            WorkflowActivityEvent.payload["status"]
                            .as_string()
                            .in_(_TERMINAL_STATUSES),
                        ),
                        WorkflowActivityEvent.seq_id,
                    ),
                    else_=None,
                )
            ).label("terminal_seq_id"),
        )
        .where(
            tuple_(WorkflowActivityEvent.thread_id, WorkflowActivityEvent.run_id).in_(
                keys
            )
        )
        .group_by(WorkflowActivityEvent.thread_id, WorkflowActivityEvent.run_id)
        .subquery()
    )
    latest_event = aliased(WorkflowActivityEvent)
    terminal_event = aliased(WorkflowActivityEvent)
    event_rows = (
        await session.execute(
            select(
                event_summary.c.thread_id,
                event_summary.c.run_id,
                latest_event.occurred_at,
                terminal_event.payload["status"].as_string(),
                terminal_event.occurred_at,
            )
            .select_from(event_summary)
            .join(
                latest_event,
                and_(
                    latest_event.thread_id == event_summary.c.thread_id,
                    latest_event.run_id == event_summary.c.run_id,
                    latest_event.seq_id == event_summary.c.latest_seq_id,
                ),
            )
            .outerjoin(
                terminal_event,
                and_(
                    terminal_event.thread_id == event_summary.c.thread_id,
                    terminal_event.run_id == event_summary.c.run_id,
                    terminal_event.seq_id == event_summary.c.terminal_seq_id,
                ),
            )
        )
    ).all()
    event_by_key = {
        (thread_id, run_id): (last_at, terminal_status, terminal_at)
        for thread_id, run_id, last_at, terminal_status, terminal_at in event_rows
    }

    records = []
    for item in work_items:
        principal_id = principal_by_thread.get(item.thread_id)
        if principal_id is None:
            continue
        key = (item.thread_id, item.run_id)
        run = run_by_key.get(key)
        last_at, terminal_status, terminal_at = event_by_key.get(
            key, (None, None, None)
        )
        records.append(
            {
                "thread_id": item.thread_id,
                "run_id": item.run_id,
                "principal_id": principal_id,
                "status": terminal_status or (run.status if run else "unknown"),
                "started_at": run.started_at if run else None,
                "updated_at": run.updated_at if run else last_at,
                "ended_at": run.ended_at if run else terminal_at,
                "input_data": None,
            }
        )

    if records:
        await session.execute(
            pg_insert(WorkflowRunHistory)
            .values(records)
            .on_conflict_do_nothing(index_elements=["thread_id", "run_id"])
        )


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
