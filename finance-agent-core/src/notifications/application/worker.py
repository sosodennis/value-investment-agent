from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from src.notifications.domain.errors import NotificationDeliveryError

from .ports import NotificationDeliveryAdapter, NotificationOutboxRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NotificationOutboxRunResult:
    claimed: int
    delivered: int
    retried: int
    dead_lettered: int


class NotificationOutboxWorker:
    def __init__(
        self,
        *,
        repository: NotificationOutboxRepository,
        adapter: NotificationDeliveryAdapter,
        batch_size: int = 50,
        lease_seconds: int = 60,
        max_attempts: int = 5,
        base_backoff_seconds: int = 1,
        max_backoff_seconds: int = 300,
    ) -> None:
        if batch_size < 1 or lease_seconds < 1 or max_attempts < 1:
            raise ValueError("outbox worker limits must be positive")
        if base_backoff_seconds < 1 or max_backoff_seconds < base_backoff_seconds:
            raise ValueError("outbox backoff limits are invalid")
        self._repository = repository
        self._adapter = adapter
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds
        self._max_attempts = max_attempts
        self._base_backoff_seconds = base_backoff_seconds
        self._max_backoff_seconds = max_backoff_seconds

    async def run_once(
        self, *, now: datetime | None = None, worker_id: str | None = None
    ) -> NotificationOutboxRunResult:
        current_time = now or datetime.now(UTC)
        current_worker = worker_id or f"notification-worker-{uuid.uuid4()}"
        deliveries = await self._repository.claim_ready(
            worker_id=current_worker,
            now=current_time,
            lease_seconds=self._lease_seconds,
            limit=self._batch_size,
        )
        delivered = 0
        retried = 0
        dead_lettered = 0
        for delivery in deliveries:
            try:
                await self._adapter.deliver(delivery=delivery)
            except NotificationDeliveryError as error:
                completion_time = current_time if now is not None else datetime.now(UTC)
                failed = await self._repository.mark_failed(
                    delivery_id=delivery.id,
                    worker_id=current_worker,
                    now=completion_time,
                    error=error.safe_code,
                    retryable=error.retryable,
                    max_attempts=self._max_attempts,
                    base_backoff_seconds=self._base_backoff_seconds,
                    max_backoff_seconds=self._max_backoff_seconds,
                )
                if failed is not None and failed.dead_lettered_at is not None:
                    dead_lettered += 1
                else:
                    retried += 1
                logger.warning(
                    "notification outbox delivery failed",
                    extra={
                        "delivery_id": delivery.id,
                        "event_id": delivery.event_id,
                        "correlation_id": delivery.correlation_id,
                        "attempt": delivery.attempts,
                        "retryable": error.retryable,
                    },
                )
            except Exception:
                completion_time = current_time if now is not None else datetime.now(UTC)
                failed = await self._repository.mark_failed(
                    delivery_id=delivery.id,
                    worker_id=current_worker,
                    now=completion_time,
                    error="delivery_failed",
                    retryable=True,
                    max_attempts=self._max_attempts,
                    base_backoff_seconds=self._base_backoff_seconds,
                    max_backoff_seconds=self._max_backoff_seconds,
                )
                if failed is not None and failed.dead_lettered_at is not None:
                    dead_lettered += 1
                else:
                    retried += 1
                logger.error(
                    "notification outbox adapter failed",
                    extra={
                        "delivery_id": delivery.id,
                        "event_id": delivery.event_id,
                        "correlation_id": delivery.correlation_id,
                    },
                )
            else:
                completion_time = current_time if now is not None else datetime.now(UTC)
                await self._repository.mark_delivered(
                    delivery_id=delivery.id,
                    worker_id=current_worker,
                    now=completion_time,
                )
                delivered += 1
        return NotificationOutboxRunResult(
            claimed=len(deliveries),
            delivered=delivered,
            retried=retried,
            dead_lettered=dead_lettered,
        )

    async def serve(
        self, *, stop_event: asyncio.Event, poll_interval_seconds: float = 1.0
    ) -> None:
        while not stop_event.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.exception("notification outbox poll failed")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_interval_seconds)
            except TimeoutError:
                continue
