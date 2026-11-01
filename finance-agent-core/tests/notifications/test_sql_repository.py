from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from src.auth.infrastructure.models import UserModel
from src.auth.infrastructure.repositories import SqlAlchemyUserRepository
from src.infrastructure.database import AsyncSessionLocal, init_db
from src.notifications.domain.entities import NotificationAction, NotificationType
from src.notifications.domain.errors import NotificationEventConflictError
from src.notifications.infrastructure.models import (
    NotificationEventModel,
    NotificationInboxItemModel,
)
from src.notifications.infrastructure.repository import SqlAlchemyNotificationRepository

pytestmark = pytest.mark.skipif(
    os.getenv("NOTIFICATION_POSTGRES_TEST") != "1",
    reason="requires the isolated PostgreSQL notification test database",
)


async def _cleanup(user_ids: set[str], event_keys: set[str]) -> None:
    async with AsyncSessionLocal() as session:
        event_ids = set(
            (
                await session.scalars(
                    select(NotificationEventModel.id).where(
                        NotificationEventModel.event_key.in_(event_keys)
                    )
                )
            ).all()
        )
        if event_ids:
            await session.execute(
                delete(NotificationInboxItemModel).where(
                    NotificationInboxItemModel.event_id.in_(event_ids)
                )
            )
            await session.execute(
                delete(NotificationEventModel).where(
                    NotificationEventModel.id.in_(event_ids)
                )
            )
        await session.execute(delete(UserModel).where(UserModel.id.in_(user_ids)))
        await session.commit()


@pytest.mark.asyncio
async def test_notification_repository_isolates_recipients_deduplicates_events_and_expires_items() -> (
    None
):
    await init_db()
    users = SqlAlchemyUserRepository()
    repository = SqlAlchemyNotificationRepository()
    user_a = await users.create_with_default_organization(
        email=f"notification-a-{uuid.uuid4()}@example.test",
        password_hash="hash",
        display_name="Notification A",
        display_name_normalized="notification a",
    )
    user_b = await users.create_with_default_organization(
        email=f"notification-b-{uuid.uuid4()}@example.test",
        password_hash="hash",
        display_name="Notification B",
        display_name_normalized="notification b",
    )
    now = datetime.now(UTC)
    event_key = f"organization.invitation:{uuid.uuid4()}"
    expired_key = f"system.expired:{uuid.uuid4()}"
    try:
        first = await repository.publish(
            event_key=event_key,
            notification_type=NotificationType.ORGANIZATION_INVITATION,
            organization_id=user_a.organization.id,
            payload={"organization_name": "Alpha"},
            action=NotificationAction(
                action_type="organization.invitation", action_ref="invitation-1"
            ),
            recipient_user_ids=(user_a.user.id,),
            occurred_at=now,
            expires_at=now + timedelta(days=7),
        )
        assert len(first) == 1
        assert first[0].organization_id == user_a.organization.id
        assert (
            await repository.list_for_recipient(
                recipient_user_id=user_b.user.id, limit=50, now=now
            )
            == []
        )

        duplicate = await repository.publish(
            event_key=event_key,
            notification_type=NotificationType.ORGANIZATION_INVITATION,
            organization_id=user_a.organization.id,
            payload={"organization_name": "Alpha"},
            action=NotificationAction(
                action_type="organization.invitation", action_ref="invitation-1"
            ),
            recipient_user_ids=(user_a.user.id, user_b.user.id),
            occurred_at=now,
            expires_at=now + timedelta(days=7),
        )
        assert {item.recipient_user_id for item in duplicate} == {
            user_a.user.id,
            user_b.user.id,
        }
        assert (
            await repository.unread_count(recipient_user_id=user_a.user.id, now=now)
            == 1
        )
        assert (
            await repository.unread_count(recipient_user_id=user_b.user.id, now=now)
            == 1
        )

        with pytest.raises(NotificationEventConflictError, match="different event"):
            await repository.publish(
                event_key=event_key,
                notification_type=NotificationType.ORGANIZATION_INVITATION,
                organization_id=user_a.organization.id,
                payload={"organization_name": "Changed"},
                action=NotificationAction(
                    action_type="organization.invitation", action_ref="invitation-1"
                ),
                recipient_user_ids=(user_a.user.id,),
                occurred_at=now,
                expires_at=now + timedelta(days=7),
            )

        read_results = await asyncio.gather(
            repository.mark_read(
                recipient_user_id=user_a.user.id, item_id=first[0].id, now=now
            ),
            repository.mark_read(
                recipient_user_id=user_a.user.id, item_id=first[0].id, now=now
            ),
        )
        assert all(
            item is not None and item.read_at is not None for item in read_results
        )
        assert (
            await repository.mark_read(
                recipient_user_id=user_b.user.id, item_id=first[0].id, now=now
            )
            is None
        )
        assert (
            await repository.unread_count(recipient_user_id=user_a.user.id, now=now)
            == 0
        )

        await repository.publish(
            event_key=expired_key,
            notification_type=NotificationType.SYSTEM,
            organization_id=None,
            payload={"message": "expired"},
            action=None,
            recipient_user_ids=(user_a.user.id,),
            occurred_at=now - timedelta(days=2),
            expires_at=now - timedelta(days=1),
        )
        visible_items = await repository.list_for_recipient(
            recipient_user_id=user_a.user.id, limit=50, now=now
        )
        assert [item.event_id for item in visible_items] == [first[0].event_id]
        assert all(
            item.expires_at is None or item.expires_at > now for item in visible_items
        )
        assert (
            await repository.unread_count(recipient_user_id=user_a.user.id, now=now)
            == 0
        )
    finally:
        await _cleanup({user_a.user.id, user_b.user.id}, {event_key, expired_key})
