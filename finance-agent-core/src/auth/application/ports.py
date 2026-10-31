from __future__ import annotations

from datetime import datetime
from typing import Protocol

from src.auth.domain.entities import (
    OrganizationMember,
    OrganizationMembership,
    OrganizationRecord,
    RegistrationRecord,
    SessionRecord,
    UserRecord,
)
from src.auth.domain.events import OrganizationLifecycleEvent


class UserRepository(Protocol):
    async def get_by_email(self, email: str) -> UserRecord | None: ...

    async def get_by_id(self, user_id: str) -> UserRecord | None: ...

    async def create_with_default_organization(
        self, *, email: str, password_hash: str
    ) -> RegistrationRecord: ...


class OrganizationRepository(Protocol):
    async def get_default_for_user(
        self, user_id: str
    ) -> OrganizationMembership | None: ...

    async def get_membership(
        self, *, user_id: str, organization_id: str
    ) -> OrganizationMembership | None: ...


class OrganizationLifecycleRepository(Protocol):
    async def create_organization(
        self, *, owner_user_id: str, name: str, now: datetime
    ) -> OrganizationMembership: ...

    async def list_for_user(self, *, user_id: str) -> list[OrganizationMembership]: ...

    async def get_organization(
        self, *, organization_id: str
    ) -> OrganizationRecord | None: ...

    async def rename_organization(
        self, *, organization_id: str, name: str, now: datetime
    ) -> OrganizationRecord: ...

    async def list_members(
        self, *, organization_id: str
    ) -> list[OrganizationMember]: ...

    async def get_member(
        self, *, organization_id: str, user_id: str
    ) -> OrganizationMember | None: ...

    async def change_membership(
        self,
        *,
        organization_id: str,
        user_id: str,
        role: str | None,
        status: str | None,
        now: datetime,
    ) -> OrganizationMember: ...

    async def transfer_ownership(
        self,
        *,
        organization_id: str,
        current_owner_user_id: str,
        target_user_id: str,
        now: datetime,
    ) -> OrganizationMember: ...

    async def append_event(self, event: OrganizationLifecycleEvent) -> None: ...


class OrganizationEventPublisher(Protocol):
    async def publish(self, event: OrganizationLifecycleEvent) -> None: ...


class SessionRepository(Protocol):
    async def create(
        self,
        *,
        user_id: str,
        active_organization_id: str,
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

    async def set_active_organization(
        self, *, session_id: str, organization_id: str, now: datetime
    ) -> bool: ...


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
