from __future__ import annotations

from src.notifications.application.service import NotificationService
from src.notifications.application.worker import NotificationOutboxWorker
from src.notifications.domain.entities import NotificationDelivery
from src.notifications.infrastructure.repository import SqlAlchemyNotificationRepository


class InAppNotificationDeliveryAdapter:
    """The durable inbox is the first delivery surface; other adapters can follow."""

    def __init__(self, *, repository: SqlAlchemyNotificationRepository) -> None:
        self._repository = repository

    async def deliver(self, *, delivery: NotificationDelivery) -> None:
        if delivery.channel != "in_app":
            from src.notifications.domain.errors import NotificationDeliveryError

            raise NotificationDeliveryError(
                "unsupported notification channel",
                retryable=False,
                safe_code="unsupported_channel",
            )
        await self._repository.deliver_in_app(delivery=delivery)


_notification_service: NotificationService | None = None
_notification_worker: NotificationOutboxWorker | None = None
_notification_repository: SqlAlchemyNotificationRepository | None = None


def _repository() -> SqlAlchemyNotificationRepository:
    global _notification_repository
    if _notification_repository is None:
        _notification_repository = SqlAlchemyNotificationRepository()
    return _notification_repository


def get_notification_service() -> NotificationService:
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService(repository=_repository())
    return _notification_service


def get_notification_worker() -> NotificationOutboxWorker:
    global _notification_worker
    if _notification_worker is None:
        repository = _repository()
        _notification_worker = NotificationOutboxWorker(
            repository=repository,
            adapter=InAppNotificationDeliveryAdapter(repository=repository),
        )
    return _notification_worker


def reset_notification_wiring() -> None:
    global _notification_service, _notification_worker, _notification_repository
    _notification_service = None
    _notification_worker = None
    _notification_repository = None
