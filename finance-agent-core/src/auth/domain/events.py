from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class OrganizationLifecycleEventType(str, Enum):
    ORGANIZATION_CREATED = "organization.created"
    ORGANIZATION_RENAMED = "organization.renamed"
    MEMBERSHIP_ROLE_CHANGED = "membership.role_changed"
    MEMBERSHIP_STATUS_CHANGED = "membership.status_changed"
    OWNERSHIP_TRANSFERRED = "organization.ownership_transferred"


@dataclass(frozen=True, slots=True)
class OrganizationLifecycleEventDraft:
    event_type: OrganizationLifecycleEventType
    actor_user_id: str
    target_user_id: str | None
    payload: dict[str, str]
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class OrganizationLifecycleEvent:
    event_type: OrganizationLifecycleEventType
    organization_id: str
    actor_user_id: str
    target_user_id: str | None
    payload: dict[str, str]
    occurred_at: datetime
