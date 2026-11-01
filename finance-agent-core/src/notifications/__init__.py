"""Recipient-private notification inbox capability."""

from .entrypoint import get_notification_service, notifications_router

__all__ = ["get_notification_service", "notifications_router"]
