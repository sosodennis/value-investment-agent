from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, text, update
from sqlalchemy.exc import DBAPIError

from src.audit.domain.entities import AuditEventDraft, AuditOutcome
from src.audit.infrastructure.models import AuditEventModel
from src.audit.infrastructure.repository import SqlAlchemyAuditRepository
from src.auth.infrastructure.models import UserModel
from src.auth.infrastructure.repositories import SqlAlchemyUserRepository
from src.infrastructure.database import AsyncSessionLocal, init_db

pytestmark = pytest.mark.skipif(
    os.getenv("AUDIT_POSTGRES_TEST") != "1",
    reason="requires the isolated PostgreSQL integration project",
)


@pytest.mark.asyncio
async def test_audit_postgres_contract_is_redacted_and_append_only() -> None:
    await init_db()
    users = SqlAlchemyUserRepository()
    repository = SqlAlchemyAuditRepository()
    user = await users.create_with_default_organization(
        email=f"audit-{uuid.uuid4()}@example.test",
        password_hash="hash",
        display_name="Audit User",
        display_name_normalized="audit user",
    )
    now = datetime.now(UTC)
    try:
        with pytest.raises(ValueError, match="audit organization does not exist"):
            await repository.append(
                event=AuditEventDraft(
                    organization_id="missing-organization",
                    actor_user_id=user.user.id,
                    action="provider.key.created",
                    outcome=AuditOutcome.SUCCESS,
                )
            )
        event = await repository.append(
            event=AuditEventDraft(
                organization_id=user.organization.id,
                actor_user_id=user.user.id,
                action="provider.key.created",
                outcome=AuditOutcome.SUCCESS,
                target_type="provider_key",
                target_id="key-1",
                correlation_id="correlation-1",
                payload={
                    "provider_api_key": "must-not-persist",
                    "status": "active",
                },
                occurred_at=now,
            )
        )
        await repository.append(
            event=AuditEventDraft(
                organization_id=user.organization.id,
                actor_system="notification-worker",
                action="notification.delivery.completed",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
            )
        )
        page = await repository.list_for_organization(
            organization_id=user.organization.id, limit=10, cursor=None
        )
        assert len(page.items) >= 3
        asserted_items = [
            item for item in page.items if item.action != "organization.created"
        ]
        assert len(asserted_items) == 2
        assert {item.actor_system for item in asserted_items} == {
            None,
            "notification-worker",
        }
        persisted = next(
            item for item in asserted_items if item.actor_user_id is not None
        )
        assert persisted.payload["provider_api_key"] == "[REDACTED]"
        assert persisted.payload["status"] == "active"
        bounded = await repository.list_for_organization(
            organization_id=user.organization.id, limit=1, cursor=None
        )
        assert len(bounded.items) == 1
        assert bounded.next_cursor is not None

        async with AsyncSessionLocal() as session:
            with pytest.raises(DBAPIError, match="append-only"):
                await session.execute(
                    update(AuditEventModel)
                    .where(AuditEventModel.id == event.id)
                    .values(action="tampered")
                )
                await session.commit()
            await session.rollback()
            with pytest.raises(DBAPIError, match="append-only"):
                await session.execute(
                    delete(AuditEventModel).where(AuditEventModel.id == event.id)
                )
                await session.commit()
            await session.rollback()
            with pytest.raises(DBAPIError, match="append-only"):
                await session.execute(text("TRUNCATE TABLE auth_audit_events"))
                await session.commit()
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    "ALTER TABLE auth_audit_events "
                    "DISABLE TRIGGER auth_audit_events_no_truncate"
                )
            )
            await session.execute(text("TRUNCATE TABLE auth_audit_events"))
            await session.execute(
                text(
                    "ALTER TABLE auth_audit_events "
                    "ENABLE TRIGGER auth_audit_events_no_truncate"
                )
            )
            await session.execute(delete(UserModel).where(UserModel.id == user.user.id))
            await session.commit()
