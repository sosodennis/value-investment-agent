from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from src.notifications.domain.entities import (
    JsonValue,
    NotificationAction,
    NotificationDeadLetter,
    NotificationDelivery,
    NotificationEnqueueResult,
    NotificationInboxItem,
    NotificationType,
)


class NotificationRepository(Protocol):
    async def enqueue(
        self,
        *,
        event_key: str,
        correlation_id: str,
        notification_type: NotificationType,
        organization_id: str | None,
        payload: dict[str, JsonValue],
        action: NotificationAction | None,
        recipient_user_ids: Sequence[str],
        occurred_at: datetime,
        expires_at: datetime | None,
    ) -> NotificationEnqueueResult: ...

    async def deliver_in_app(
        self, *, delivery: NotificationDelivery
    ) -> NotificationInboxItem | None: ...

    async def list_for_recipient(
        self, *, recipient_user_id: str, limit: int, now: datetime
    ) -> list[NotificationInboxItem]: ...

    async def unread_count(self, *, recipient_user_id: str, now: datetime) -> int: ...

    async def mark_read(
        self, *, recipient_user_id: str, item_id: str, now: datetime
    ) -> NotificationInboxItem | None: ...


class NotificationTransaction(Protocol):
    async def enqueue(
        self,
        *,
        event_key: str,
        correlation_id: str,
        notification_type: NotificationType,
        organization_id: str | None,
        payload: dict[str, JsonValue],
        action: NotificationAction | None,
        recipient_user_ids: Sequence[str],
        occurred_at: datetime,
        expires_at: datetime | None,
    ) -> NotificationEnqueueResult: ...


class NotificationDeliveryAdapter(Protocol):
    async def deliver(self, *, delivery: NotificationDelivery) -> None: ...


class NotificationOutboxRepository(Protocol):
    async def claim_ready(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
        limit: int,
    ) -> list[NotificationDelivery]: ...

    async def mark_delivered(
        self, *, delivery_id: str, worker_id: str, now: datetime
    ) -> bool: ...

    async def mark_failed(
        self,
        *,
        delivery_id: str,
        worker_id: str,
        now: datetime,
        error: str,
        retryable: bool,
        max_attempts: int,
        base_backoff_seconds: int,
        max_backoff_seconds: int,
    ) -> NotificationDelivery | None: ...

    async def list_dead_letters(
        self, *, limit: int
    ) -> list[NotificationDeadLetter]: ...

    async def replay_dead_letter(self, *, delivery_id: str, now: datetime) -> bool: ...
