from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TypeAlias

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class AuditActorType(str, Enum):
    USER = "user"
    SYSTEM = "system"


class AuditOutcome(str, Enum):
    SUCCESS = "success"
    DENIED = "denied"
    FAILURE = "failure"


@dataclass(frozen=True, slots=True)
class AuditEventDraft:
    organization_id: str
    action: str
    outcome: AuditOutcome
    actor_user_id: str | None = None
    actor_system: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    correlation_id: str | None = None
    payload: dict[str, JsonValue] = field(default_factory=dict)
    occurred_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: str
    organization_id: str
    actor_type: AuditActorType
    actor_user_id: str | None
    actor_system: str | None
    action: str
    target_type: str | None
    target_id: str | None
    outcome: AuditOutcome
    correlation_id: str
    payload: dict[str, JsonValue]
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class AuditEventPage:
    items: tuple[AuditEvent, ...]
    next_cursor: tuple[datetime, str] | None
