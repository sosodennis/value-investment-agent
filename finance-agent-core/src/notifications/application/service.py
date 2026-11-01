from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from src.notifications.domain.entities import (
    NotificationAction,
    NotificationInboxItem,
    NotificationType,
    require_utc,
    validate_notification_action,
    validate_notification_payload,
)
from src.notifications.domain.errors import NotificationNotFoundError

from .ports import NotificationDeliveryAdapter, NotificationRepository


class NotificationService:
    def __init__(
        self,
        *,
        repository: NotificationRepository,
        delivery: NotificationDeliveryAdapter,
    ) -> None:
        self._repository = repository
        self._delivery = delivery

    async def publish(
        self,
        *,
        event_key: str,
        notification_type: NotificationType,
        organization_id: str | None,
        payload: object,
        action: NotificationAction | None,
        recipient_user_ids: Sequence[str],
        occurred_at: datetime,
        expires_at: datetime | None,
    ) -> list[NotificationInboxItem]:
        if not event_key.strip() or len(event_key) > 255:
            raise ValueError("notification event key is required")
        validate_notification_action(action)
        recipients = tuple(dict.fromkeys(recipient_user_ids))
        if not recipients or any(not recipient.strip() for recipient in recipients):
            raise ValueError("notification requires at least one recipient")
        validated_payload = validate_notification_payload(payload)
        occurred_at = require_utc(occurred_at, field_name="occurred_at")
        expires_at = (
            require_utc(expires_at, field_name="expires_at")
            if expires_at is not None
            else None
        )
        items = await self._repository.publish(
            event_key=event_key,
            notification_type=notification_type,
            organization_id=organization_id,
            payload=validated_payload,
            action=action,
            recipient_user_ids=recipients,
            occurred_at=occurred_at,
            expires_at=expires_at,
        )
        for item in items:
            await self._delivery.deliver(item=item)
        return items

    async def list_for_recipient(
        self, *, recipient_user_id: str, limit: int, now: datetime
    ) -> list[NotificationInboxItem]:
        return await self._repository.list_for_recipient(
            recipient_user_id=recipient_user_id,
            limit=limit,
            now=require_utc(now, field_name="now"),
        )

    async def unread_count(self, *, recipient_user_id: str, now: datetime) -> int:
        return await self._repository.unread_count(
            recipient_user_id=recipient_user_id,
            now=require_utc(now, field_name="now"),
        )

    async def mark_read(
        self, *, recipient_user_id: str, item_id: str, now: datetime
    ) -> NotificationInboxItem:
        item = await self._repository.mark_read(
            recipient_user_id=recipient_user_id,
            item_id=item_id,
            now=require_utc(now, field_name="now"),
        )
        if item is None:
            raise NotificationNotFoundError("notification not found")
        return item
