from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class UserRecord:
    id: str
    email: str
    password_hash: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SessionRecord:
    id: str
    user_id: str
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


@dataclass(frozen=True, slots=True)
class OwnedResource:
    resource_type: str
    resource_id: str
    user_id: str
