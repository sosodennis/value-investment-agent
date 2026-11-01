from __future__ import annotations

from src.notifications.application.service import NotificationService
from src.notifications.domain.entities import NotificationInboxItem
from src.notifications.infrastructure.repository import SqlAlchemyNotificationRepository


class InAppNotificationDeliveryAdapter:
    """The durable inbox is the first delivery surface; other adapters can follow."""

    async def deliver(self, *, item: NotificationInboxItem) -> None:
        return None


_notification_service: NotificationService | None = None


def get_notification_service() -> NotificationService:
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService(
            repository=SqlAlchemyNotificationRepository(),
            delivery=InAppNotificationDeliveryAdapter(),
        )
    return _notification_service


def reset_notification_wiring() -> None:
    global _notification_service
    _notification_service = None
