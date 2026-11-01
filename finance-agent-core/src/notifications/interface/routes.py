from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from src.auth.domain.entities import AuthenticatedActorContext
from src.notifications.application.service import NotificationService
from src.notifications.application.wiring import get_notification_service
from src.notifications.domain.entities import NotificationInboxItem
from src.notifications.domain.errors import NotificationNotFoundError

from .contracts import (
    NotificationActionResponse,
    NotificationListResponse,
    NotificationResponse,
    NotificationUnreadCountResponse,
)
from .dependencies import (
    current_notification_recipient,
    current_notification_recipient_mutation,
)

router = APIRouter(prefix="/api/v1/notifications", tags=["Notifications"])


def _response(item: NotificationInboxItem) -> NotificationResponse:
    return NotificationResponse(
        notification_id=item.id,
        event_id=item.event_id,
        type=item.notification_type,
        organization_id=item.organization_id,
        payload=item.payload,
        action=(
            NotificationActionResponse(
                action_type=item.action.action_type,
                action_ref=item.action.action_ref,
            )
            if item.action
            else None
        ),
        read_at=item.read_at,
        created_at=item.created_at,
        expires_at=item.expires_at,
    )


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    limit: int = Query(default=50, ge=1, le=100),
    actor: AuthenticatedActorContext = Depends(current_notification_recipient),
    service: NotificationService = Depends(get_notification_service),
) -> NotificationListResponse:
    now = datetime.now(UTC)
    items = await service.list_for_recipient(
        recipient_user_id=actor.user.id, limit=limit, now=now
    )
    unread_count = await service.unread_count(recipient_user_id=actor.user.id, now=now)
    return NotificationListResponse(
        items=[_response(item) for item in items], unread_count=unread_count
    )


@router.get("/unread-count", response_model=NotificationUnreadCountResponse)
async def unread_count(
    actor: AuthenticatedActorContext = Depends(current_notification_recipient),
    service: NotificationService = Depends(get_notification_service),
) -> NotificationUnreadCountResponse:
    return NotificationUnreadCountResponse(
        unread_count=await service.unread_count(
            recipient_user_id=actor.user.id, now=datetime.now(UTC)
        )
    )


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    notification_id: str,
    actor: AuthenticatedActorContext = Depends(current_notification_recipient_mutation),
    service: NotificationService = Depends(get_notification_service),
) -> NotificationResponse:
    try:
        item = await service.mark_read(
            recipient_user_id=actor.user.id,
            item_id=notification_id,
            now=datetime.now(UTC),
        )
    except NotificationNotFoundError as error:
        raise HTTPException(status_code=404, detail="notification_not_found") from error
    return _response(item)
