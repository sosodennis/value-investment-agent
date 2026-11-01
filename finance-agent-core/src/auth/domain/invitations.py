from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum


class InvitationStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    REVOKED = "revoked"


class InvitationOperation(str, Enum):
    CREATE = "create"
    ACCEPT = "accept"
    DECLINE = "decline"
    REVOKE = "revoke"
    RESEND = "resend"


@dataclass(frozen=True, slots=True)
class InvitationRecord:
    id: str
    organization_id: str
    organization_name: str
    inviter_user_id: str
    inviter_display_name: str
    recipient_user_id: str
    recipient_display_name: str
    requested_role: str
    status: InvitationStatus
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    revision: int
    notification_event_id: str

    @property
    def is_pending(self) -> bool:
        return self.status is InvitationStatus.PENDING

    @property
    def is_expired(self) -> bool:
        return self.status is InvitationStatus.EXPIRED

    def with_status(
        self, status: InvitationStatus, *, now: datetime
    ) -> InvitationRecord:
        return InvitationRecord(
            id=self.id,
            organization_id=self.organization_id,
            organization_name=self.organization_name,
            inviter_user_id=self.inviter_user_id,
            inviter_display_name=self.inviter_display_name,
            recipient_user_id=self.recipient_user_id,
            recipient_display_name=self.recipient_display_name,
            requested_role=self.requested_role,
            status=status,
            created_at=self.created_at,
            updated_at=now,
            expires_at=self.expires_at,
            revision=self.revision,
            notification_event_id=self.notification_event_id,
        )


def require_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)
