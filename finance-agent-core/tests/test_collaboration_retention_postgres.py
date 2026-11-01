from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from src.auth.application.invitation_retention import run_invitation_retention
from src.auth.infrastructure.models import InvitationModel, OrganizationModel, UserModel
from src.auth.infrastructure.retention_repository import (
    SqlAlchemyInvitationRetentionRepository,
)
from src.infrastructure.database import AsyncSessionLocal, init_db
from src.notifications.application.retention import run_notification_retention
from src.notifications.domain.entities import NotificationDeliveryStatus
from src.notifications.infrastructure.models import (
    NotificationEventModel,
    NotificationInboxItemModel,
    NotificationOutboxModel,
)
from src.notifications.infrastructure.repository import SqlAlchemyNotificationRepository

pytestmark = pytest.mark.skipif(
    os.getenv("COLLABORATION_RETENTION_POSTGRES_TEST") != "1",
    reason="requires the isolated collaboration PostgreSQL service",
)


@pytest.mark.asyncio
async def test_retention_keeps_active_invites_and_leased_deliveries() -> None:
    await init_db()
    now = datetime(2026, 1, 1)
    suffix = uuid.uuid4().hex
    organization_id = f"retention-org-{suffix}"
    actor_id = f"retention-actor-{suffix}"
    expired_user_id = f"retention-expired-{suffix}"
    old_user_id = f"retention-old-{suffix}"
    active_user_id = f"retention-active-{suffix}"
    expired_event_id = f"retention-expired-event-{suffix}"
    old_event_id = f"retention-old-event-{suffix}"
    active_event_id = f"retention-active-event-{suffix}"
    leased_event_id = f"retention-leased-event-{suffix}"

    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(
                OrganizationModel(
                    id=organization_id, name="Retention Test", created_at=now
                )
            )
            for user_id, label in (
                (actor_id, "actor"),
                (expired_user_id, "expired"),
                (old_user_id, "old"),
                (active_user_id, "active"),
            ):
                session.add(
                    UserModel(
                        id=user_id,
                        email=f"{user_id}@example.test",
                        display_name=label,
                        display_name_normalized=label,
                        password_hash="unused",
                        created_at=now,
                    )
                )
            await session.flush()
            session.add_all(
                [
                    NotificationEventModel(
                        id=expired_event_id,
                        event_key=f"{expired_event_id}:key",
                        correlation_id="retention-trace",
                        notification_type="organization.invitation",
                        organization_id=organization_id,
                        payload={"status": "pending"},
                        occurred_at=now - timedelta(days=7),
                        expires_at=now - timedelta(minutes=1),
                        created_at=now - timedelta(days=7),
                    ),
                    NotificationEventModel(
                        id=old_event_id,
                        event_key=f"{old_event_id}:key",
                        correlation_id="retention-trace",
                        notification_type="organization.invitation",
                        organization_id=organization_id,
                        payload={"status": "revoked"},
                        occurred_at=now - timedelta(days=100),
                        expires_at=None,
                        created_at=now - timedelta(days=100),
                    ),
                    NotificationEventModel(
                        id=active_event_id,
                        event_key=f"{active_event_id}:key",
                        correlation_id="retention-trace",
                        notification_type="organization.invitation",
                        organization_id=organization_id,
                        payload={"status": "pending"},
                        occurred_at=now,
                        expires_at=now + timedelta(days=7),
                        created_at=now,
                    ),
                    NotificationEventModel(
                        id=leased_event_id,
                        event_key=f"{leased_event_id}:key",
                        correlation_id="retention-trace",
                        notification_type="system",
                        organization_id=organization_id,
                        payload={"message": "safe"},
                        occurred_at=now - timedelta(days=100),
                        expires_at=None,
                        created_at=now - timedelta(days=100),
                    ),
                ]
            )
            session.add_all(
                [
                    InvitationModel(
                        id=f"invite-expired-{suffix}",
                        organization_id=organization_id,
                        inviter_user_id=actor_id,
                        recipient_user_id=expired_user_id,
                        requested_role="member",
                        status="pending",
                        created_at=now - timedelta(days=7),
                        updated_at=now - timedelta(days=7),
                        expires_at=now - timedelta(minutes=1),
                        revision=1,
                        notification_event_id=expired_event_id,
                    ),
                    InvitationModel(
                        id=f"invite-old-{suffix}",
                        organization_id=organization_id,
                        inviter_user_id=actor_id,
                        recipient_user_id=old_user_id,
                        requested_role="member",
                        status="revoked",
                        created_at=now - timedelta(days=100),
                        updated_at=now - timedelta(days=91),
                        expires_at=now - timedelta(days=93),
                        revision=1,
                        notification_event_id=old_event_id,
                    ),
                    InvitationModel(
                        id=f"invite-active-{suffix}",
                        organization_id=organization_id,
                        inviter_user_id=actor_id,
                        recipient_user_id=active_user_id,
                        requested_role="member",
                        status="pending",
                        created_at=now,
                        updated_at=now,
                        expires_at=now + timedelta(days=7),
                        revision=1,
                        notification_event_id=active_event_id,
                    ),
                ]
            )
            session.add(
                NotificationInboxItemModel(
                    id=f"inbox-old-{suffix}",
                    event_id=old_event_id,
                    recipient_user_id=old_user_id,
                    created_at=now - timedelta(days=100),
                )
            )
            session.add(
                NotificationOutboxModel(
                    id=f"outbox-old-{suffix}",
                    event_id=old_event_id,
                    recipient_user_id=old_user_id,
                    channel="in_app",
                    idempotency_key=f"{old_event_id}:old",
                    status=NotificationDeliveryStatus.DELIVERED.value,
                    attempts=1,
                    next_attempt_at=now - timedelta(days=100),
                    delivered_at=now - timedelta(days=100),
                    created_at=now - timedelta(days=100),
                )
            )
            session.add(
                NotificationOutboxModel(
                    id=f"outbox-leased-{suffix}",
                    event_id=leased_event_id,
                    recipient_user_id=active_user_id,
                    channel="in_app",
                    idempotency_key=f"{leased_event_id}:active",
                    status=NotificationDeliveryStatus.LEASED.value,
                    attempts=1,
                    next_attempt_at=now,
                    lease_owner="retention-test-worker",
                    lease_expires_at=now + timedelta(minutes=1),
                    created_at=now - timedelta(days=100),
                )
            )

    invitation_result = await run_invitation_retention(
        SqlAlchemyInvitationRetentionRepository(), now=now, terminal_retention_days=90
    )
    notification_result = await run_notification_retention(
        SqlAlchemyNotificationRepository(),
        now=now,
        retention_days=90,
        expired_retention_days=30,
    )

    async with AsyncSessionLocal() as session:
        expired_invitation = await session.scalar(
            select(InvitationModel).where(
                InvitationModel.id == f"invite-expired-{suffix}"
            )
        )
        active_invitation = await session.scalar(
            select(InvitationModel).where(
                InvitationModel.id == f"invite-active-{suffix}"
            )
        )
        expired_event = await session.get(NotificationEventModel, expired_event_id)
        active_event = await session.get(NotificationEventModel, active_event_id)
        old_event = await session.get(NotificationEventModel, old_event_id)
        leased_event = await session.get(NotificationEventModel, leased_event_id)
        old_inbox = await session.get(NotificationInboxItemModel, f"inbox-old-{suffix}")

    assert invitation_result.expired == 1
    assert invitation_result.purged == 1
    assert notification_result.deleted_events == 1
    assert expired_invitation is not None and expired_invitation.status == "expired"
    assert expired_event is not None and expired_event.expires_at is None
    assert active_invitation is not None and active_invitation.status == "pending"
    assert active_event is not None
    assert old_event is None and old_inbox is None
    assert leased_event is not None
