"""Bind thread ownership to one organization without creating synthetic runs."""

from __future__ import annotations

from sqlalchemy import text

from src.infrastructure.database import AsyncSessionLocal

THREAD_OWNERSHIP_MIGRATION_ID = "20261124_thread_organization_scope_v1"


async def run_thread_ownership_migration() -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                text(
                    "ALTER TABLE auth_owned_resources ADD COLUMN IF NOT EXISTS organization_id VARCHAR"
                )
            )
            await session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_auth_owned_resources_organization_id ON auth_owned_resources (organization_id)"
                )
            )
            await session.execute(
                text("""
                UPDATE auth_owned_resources AS owned
                SET organization_id = proven.organization_id
                FROM (
                    SELECT history.thread_id, MIN(history.organization_id) AS organization_id
                    FROM workflow_run_history AS history
                    JOIN auth_owned_resources AS current_owner
                      ON current_owner.resource_type = 'thread'
                     AND current_owner.resource_id = history.thread_id
                    GROUP BY history.thread_id
                    HAVING COUNT(DISTINCT history.organization_id) = 1
                       AND BOOL_AND(history.organization_id IS NOT NULL
                                    AND history.organization_id <> 'unscoped'
                                    AND history.organization_id <> '')
                       AND BOOL_AND(history.principal_id = current_owner.user_id)
                ) AS proven
                WHERE owned.resource_type = 'thread'
                  AND owned.resource_id = proven.thread_id
                  AND owned.organization_id IS NULL
            """)
            )
            await session.execute(
                text("""
                INSERT INTO database_migrations (migration_id, initialized_at, completed_at)
                VALUES (:migration_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (migration_id) DO UPDATE SET completed_at = EXCLUDED.completed_at
            """),
                {"migration_id": THREAD_OWNERSHIP_MIGRATION_ID},
            )
