from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    organization_id: str
    actor_type: Literal["user", "system"]
    actor_user_id: str | None
    actor_system: str | None
    action: str
    target_type: str | None
    target_id: str | None
    outcome: Literal["success", "denied", "failure"]
    correlation_id: str
    payload: dict[str, object]
    occurred_at: datetime


class AuditEventListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AuditEventResponse]
    next_cursor: str | None = None
