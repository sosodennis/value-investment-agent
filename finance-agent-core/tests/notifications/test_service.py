from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.notifications.application.service import NotificationService
from src.notifications.domain.entities import (
    NotificationAction,
    NotificationInboxItem,
    NotificationType,
)
from src.notifications.domain.errors import NotificationPayloadError


class FakeRepository:
    def __init__(self) -> None:
        self.published: list[dict[str, object]] = []

    async def publish(self, **kwargs):
        self.published.append(kwargs)
        return [
            NotificationInboxItem(
                id="inbox-1",
                event_id="event-1",
                recipient_user_id=kwargs["recipient_user_ids"][0],
                notification_type=kwargs["notification_type"],
                organization_id=kwargs["organization_id"],
                payload=kwargs["payload"],
                action=kwargs["action"],
                read_at=None,
                created_at=kwargs["occurred_at"],
                expires_at=kwargs["expires_at"],
            )
        ]

    async def list_for_recipient(self, **kwargs):
        return []

    async def unread_count(self, **kwargs):
        return 0

    async def mark_read(self, **kwargs):
        return None


class FakeDelivery:
    def __init__(self) -> None:
        self.items: list[NotificationInboxItem] = []

    async def deliver(self, *, item: NotificationInboxItem) -> None:
        self.items.append(item)


@pytest.mark.asyncio
async def test_publish_deduplicates_recipients_and_delivers_persisted_inbox_items() -> (
    None
):
    repository = FakeRepository()
    delivery = FakeDelivery()
    service = NotificationService(repository=repository, delivery=delivery)
    now = datetime(2026, 1, 1, tzinfo=UTC)

    items = await service.publish(
        event_key="organization.invitation:invitation-1",
        notification_type=NotificationType.ORGANIZATION_INVITATION,
        organization_id="organization-1",
        payload={"organization_name": "Alpha team"},
        action=NotificationAction(
            action_type="organization.invitation", action_ref="invitation-1"
        ),
        recipient_user_ids=("user-1", "user-1"),
        occurred_at=now,
        expires_at=now + timedelta(days=7),
    )

    assert items[0].recipient_user_id == "user-1"
    assert repository.published[0]["recipient_user_ids"] == ("user-1",)
    assert delivery.items == items


@pytest.mark.asyncio
async def test_publish_rejects_credential_like_payload_fields() -> None:
    service = NotificationService(repository=FakeRepository(), delivery=FakeDelivery())

    with pytest.raises(NotificationPayloadError, match="token"):
        await service.publish(
            event_key="event-1",
            notification_type=NotificationType.SYSTEM,
            organization_id=None,
            payload={"invitation_token": "do-not-store"},
            action=None,
            recipient_user_ids=("user-1",),
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            expires_at=None,
        )


@pytest.mark.asyncio
async def test_publish_rejects_sensitive_values_and_unsafe_action_references() -> None:
    service = NotificationService(repository=FakeRepository(), delivery=FakeDelivery())

    with pytest.raises(NotificationPayloadError, match="credential-like"):
        await service.publish(
            event_key="event-sensitive-value",
            notification_type=NotificationType.SYSTEM,
            organization_id=None,
            payload={"message": "invite token=secret-value"},
            action=None,
            recipient_user_ids=("user-1",),
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            expires_at=None,
        )

    with pytest.raises(ValueError, match="action reference"):
        await service.publish(
            event_key="event-unsafe-action",
            notification_type=NotificationType.SYSTEM,
            organization_id=None,
            payload={"message": "safe"},
            action=NotificationAction(
                action_type="system.notice", action_ref="https://example.test/invite"
            ),
            recipient_user_ids=("user-1",),
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            expires_at=None,
        )

    with pytest.raises(ValueError, match="action type"):
        await service.publish(
            event_key="event-long-action-type",
            notification_type=NotificationType.SYSTEM,
            organization_id=None,
            payload={"message": "safe"},
            action=NotificationAction(
                action_type="a" * 121, action_ref="opaque-reference"
            ),
            recipient_user_ids=("user-1",),
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            expires_at=None,
        )


@pytest.mark.asyncio
async def test_publish_requires_utc_timestamps() -> None:
    service = NotificationService(repository=FakeRepository(), delivery=FakeDelivery())

    with pytest.raises(ValueError, match="occurred_at"):
        await service.publish(
            event_key="event-naive-time",
            notification_type=NotificationType.SYSTEM,
            organization_id=None,
            payload={"message": "safe"},
            action=None,
            recipient_user_ids=("user-1",),
            occurred_at=datetime(2026, 1, 1),
            expires_at=None,
        )
