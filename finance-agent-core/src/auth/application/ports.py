from __future__ import annotations

from datetime import datetime
from typing import Protocol

from src.auth.domain.entities import SessionRecord, UserRecord


class UserRepository(Protocol):
    async def get_by_email(self, email: str) -> UserRecord | None: ...

    async def get_by_id(self, user_id: str) -> UserRecord | None: ...

    async def create(self, *, email: str, password_hash: str) -> UserRecord: ...


class SessionRepository(Protocol):
    async def create(
        self,
        *,
        user_id: str,
        token_hash: str,
        csrf_token_hash: str,
        expires_at: datetime,
    ) -> SessionRecord: ...

    async def get_active_by_token_hash(
        self,
        *,
        token_hash: str,
        now: datetime,
    ) -> SessionRecord | None: ...

    async def revoke(self, *, session_id: str, revoked_at: datetime) -> None: ...


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password: str, password_hash: str) -> bool: ...


class OwnershipRepository(Protocol):
    async def claim(
        self,
        *,
        resource_type: str,
        resource_id: str,
        user_id: str,
    ) -> bool: ...

    async def owner_of(
        self,
        *,
        resource_type: str,
        resource_id: str,
    ) -> str | None: ...

    async def list_owned_ids(
        self,
        *,
        resource_type: str,
        user_id: str,
    ) -> set[str]: ...

    async def release(self, *, resource_type: str, resource_id: str) -> None: ...
