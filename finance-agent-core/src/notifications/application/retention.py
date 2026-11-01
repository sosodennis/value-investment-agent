from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from src.notifications.application.ports import NotificationRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NotificationRetentionResult:
    deleted_events: int
    batch_limit: int


async def run_notification_retention(
    repository: NotificationRepository,
    *,
    now: datetime | None = None,
    batch_limit: int = 100,
    retention_days: int = 90,
    expired_retention_days: int = 30,
) -> NotificationRetentionResult:
    """Delete one bounded batch of expired inbox events and their deliveries."""

    current_time = now or datetime.now(UTC)
    if not 1 <= batch_limit <= 1_000:
        raise ValueError("notification retention batch size is invalid")
    if retention_days < 1 or expired_retention_days < 1:
        raise ValueError("notification retention periods must be positive")
    deleted_events = await repository.purge_expired(
        created_before=current_time - timedelta(days=retention_days),
        expired_before=current_time - timedelta(days=expired_retention_days),
        limit=batch_limit,
    )
    logger.info(
        "notification retention batch completed",
        extra={"deleted_events": deleted_events, "batch_limit": batch_limit},
    )
    return NotificationRetentionResult(
        deleted_events=deleted_events, batch_limit=batch_limit
    )
