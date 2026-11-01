from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from src.notifications.application.worker import NotificationOutboxWorker
from src.notifications.domain.entities import (
    NotificationAction,
    NotificationDelivery,
    NotificationDeliveryStatus,
    NotificationType,
)
from src.notifications.domain.errors import NotificationDeliveryError


def _delivery() -> NotificationDelivery:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return NotificationDelivery(
        id="delivery-1",
        event_id="event-1",
        event_key="system:event-1",
        correlation_id="correlation-1",
        recipient_user_id="user-1",
        channel="in_app",
        idempotency_key="event-1:in_app:user-1",
        notification_type=NotificationType.SYSTEM,
        organization_id=None,
        payload={"message": "safe"},
        action=NotificationAction(
            action_type="system.notice", action_ref="opaque-reference"
        ),
        occurred_at=now,
        expires_at=now + timedelta(days=1),
        status=NotificationDeliveryStatus.PENDING,
        attempts=0,
        next_attempt_at=now,
        lease_owner=None,
        lease_expires_at=None,
        last_error=None,
        delivered_at=None,
        dead_lettered_at=None,
    )


class FakeOutbox:
    def __init__(self) -> None:
        self.delivery = _delivery()
        self.failed: list[dict[str, object]] = []
        self.delivered = False
        self.replayed = False

    async def claim_ready(self, *, worker_id, now, lease_seconds, limit):
        if self.delivery.status is not NotificationDeliveryStatus.PENDING:
            return []
        self.delivery = replace(
            self.delivery,
            status=NotificationDeliveryStatus.LEASED,
            attempts=self.delivery.attempts + 1,
            lease_owner=worker_id,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
        )
        return [self.delivery]

    async def mark_delivered(self, *, delivery_id, worker_id, now):
        self.delivered = True
        self.delivery = replace(
            self.delivery,
            status=NotificationDeliveryStatus.DELIVERED,
            delivered_at=now,
            lease_owner=None,
            lease_expires_at=None,
        )
        return True

    async def mark_failed(
        self,
        *,
        delivery_id,
        worker_id,
        now,
        error,
        retryable,
        max_attempts,
        base_backoff_seconds,
        max_backoff_seconds,
    ):
        terminal = not retryable or self.delivery.attempts >= max_attempts
        status = (
            NotificationDeliveryStatus.DEAD_LETTER
            if terminal
            else NotificationDeliveryStatus.PENDING
        )
        next_attempt_at = now + timedelta(
            seconds=0 if terminal else base_backoff_seconds
        )
        self.failed.append(
            {"error": error, "retryable": retryable, "next_attempt_at": next_attempt_at}
        )
        self.delivery = replace(
            self.delivery,
            status=status,
            next_attempt_at=next_attempt_at,
            last_error=error,
            dead_lettered_at=now if terminal else None,
            lease_owner=None,
            lease_expires_at=None,
        )
        return self.delivery


class FailingAdapter:
    def __init__(self, failures: int) -> None:
        self.failures = failures

    async def deliver(self, *, delivery):
        if self.failures:
            self.failures -= 1
            raise NotificationDeliveryError(
                "adapter unavailable", safe_code="adapter_unavailable"
            )


class GenericFailingAdapter:
    async def deliver(self, *, delivery):
        raise RuntimeError("secret-token=must-not-be-logged")


@pytest.mark.asyncio
async def test_worker_retries_with_backoff_and_dead_letters_after_limit() -> None:
    repository = FakeOutbox()
    worker = NotificationOutboxWorker(
        repository=repository,
        adapter=FailingAdapter(failures=2),
        max_attempts=2,
        base_backoff_seconds=3,
        max_backoff_seconds=30,
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)

    first = await worker.run_once(now=now, worker_id="worker-a")
    assert first.retried == 1
    assert repository.failed[0]["next_attempt_at"] == now + timedelta(seconds=3)

    second = await worker.run_once(now=now + timedelta(seconds=3), worker_id="worker-a")
    assert second.dead_lettered == 1
    assert repository.delivery.status is NotificationDeliveryStatus.DEAD_LETTER
    assert repository.delivery.last_error == "adapter_unavailable"


@pytest.mark.asyncio
async def test_worker_does_not_log_or_persist_raw_generic_adapter_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    repository = FakeOutbox()
    worker = NotificationOutboxWorker(
        repository=repository,
        adapter=GenericFailingAdapter(),
        max_attempts=1,
    )
    caplog.set_level(logging.ERROR)

    result = await worker.run_once(
        now=datetime(2026, 1, 1, tzinfo=UTC), worker_id="worker-a"
    )

    assert result.dead_lettered == 1
    assert repository.delivery.last_error == "delivery_failed"
    assert "secret-token" not in caplog.text
    assert any(
        record.__dict__.get("correlation_id") == "correlation-1"
        for record in caplog.records
    )
