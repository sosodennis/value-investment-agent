from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.notifications.domain.entities import NotificationType


class NotificationActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: str = Field(min_length=1, max_length=120)
    action_ref: str = Field(min_length=1, max_length=255)


class NotificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notification_id: str
    event_id: str
    type: NotificationType
    organization_id: str | None
    payload: dict[str, object]
    action: NotificationActionResponse | None
    read_at: datetime | None
    created_at: datetime
    expires_at: datetime | None


class NotificationListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[NotificationResponse]
    unread_count: int


class NotificationUnreadCountResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unread_count: int
