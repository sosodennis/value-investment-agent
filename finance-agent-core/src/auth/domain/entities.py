from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


@dataclass(frozen=True, slots=True)
class UserRecord:
    id: str
    email: str
    password_hash: str
    created_at: datetime
    display_name: str


@dataclass(frozen=True, slots=True)
class DirectoryUser:
    user_id: str
    display_name: str


@dataclass(frozen=True, slots=True)
class DirectoryPage:
    items: tuple[DirectoryUser, ...]
    next_cursor: str | None


class MembershipStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REMOVED = "removed"


class MembershipRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


@dataclass(frozen=True, slots=True)
class OrganizationRecord:
    id: str
    name: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class MembershipRecord:
    id: str
    organization_id: str
    user_id: str
    role: MembershipRole
    status: MembershipStatus
    created_at: datetime
    updated_at: datetime

    @property
    def is_active(self) -> bool:
        return self.status is MembershipStatus.ACTIVE


@dataclass(frozen=True, slots=True)
class OrganizationMembership:
    organization: OrganizationRecord
    membership: MembershipRecord


@dataclass(frozen=True, slots=True)
class OrganizationMember:
    user: UserRecord
    membership: MembershipRecord


@dataclass(frozen=True, slots=True)
class RegistrationRecord:
    user: UserRecord
    organization: OrganizationRecord
    membership: MembershipRecord


@dataclass(frozen=True, slots=True)
class SessionRecord:
    id: str
    user_id: str
    active_organization_id: str
    token_hash: str
    csrf_token_hash: str
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AuthSession:
    user: UserRecord
    session_token: str
    csrf_token: str
    expires_at: datetime
    active_organization_id: str


@dataclass(frozen=True, slots=True)
class AuthenticatedContext:
    user: UserRecord
    session: SessionRecord
    membership: MembershipRecord


@dataclass(frozen=True, slots=True)
class AuthenticatedActorContext:
    user: UserRecord
    session: SessionRecord


@dataclass(frozen=True, slots=True)
class OwnedResource:
    resource_type: str
    resource_id: str
    user_id: str
