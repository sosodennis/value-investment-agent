from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from src.notifications.domain.entities import (
    JsonValue,
    NotificationAction,
    NotificationInboxItem,
    NotificationType,
)


class NotificationRepository(Protocol):
    async def publish(
        self,
        *,
        event_key: str,
        notification_type: NotificationType,
        organization_id: str | None,
        payload: dict[str, JsonValue],
        action: NotificationAction | None,
        recipient_user_ids: Sequence[str],
        occurred_at: datetime,
        expires_at: datetime | None,
    ) -> list[NotificationInboxItem]: ...

    async def list_for_recipient(
        self, *, recipient_user_id: str, limit: int, now: datetime
    ) -> list[NotificationInboxItem]: ...

    async def unread_count(self, *, recipient_user_id: str, now: datetime) -> int: ...

    async def mark_read(
        self, *, recipient_user_id: str, item_id: str, now: datetime
    ) -> NotificationInboxItem | None: ...


class NotificationDeliveryAdapter(Protocol):
    async def deliver(self, *, item: NotificationInboxItem) -> None: ...
