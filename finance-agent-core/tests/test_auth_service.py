from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from src.auth.application.errors import (
    InvalidCredentialsError,
    InvalidOrganizationContextError,
    RegistrationConflictError,
)
from src.auth.application.service import AuthService, hash_secret
from src.auth.domain.entities import (
    MembershipRecord,
    MembershipRole,
    MembershipStatus,
    OrganizationMembership,
    OrganizationRecord,
    RegistrationRecord,
    SessionRecord,
    UserRecord,
)


class MemoryUsers:
    def __init__(self) -> None:
        self.users: dict[str, UserRecord] = {}
        self.organizations: dict[str, OrganizationMembership] = {}

    async def get_by_email(self, email: str) -> UserRecord | None:
        return next((user for user in self.users.values() if user.email == email), None)

    async def get_by_id(self, user_id: str) -> UserRecord | None:
        return self.users.get(user_id)

    async def create_with_default_organization(
        self,
        *,
        email: str,
        password_hash: str,
        display_name: str,
        display_name_normalized: str,
    ) -> RegistrationRecord:
        user = UserRecord(
            id=f"user-{len(self.users) + 1}",
            email=email,
            password_hash=password_hash,
            created_at=datetime.utcnow(),
            display_name=display_name,
        )
        organization = OrganizationRecord(
            id=f"organization-{len(self.organizations) + 1}",
            name="Personal organization",
            created_at=user.created_at,
        )
        membership = MembershipRecord(
            id=f"membership-{len(self.organizations) + 1}",
            organization_id=organization.id,
            user_id=user.id,
            role=MembershipRole.OWNER,
            status=MembershipStatus.ACTIVE,
            created_at=user.created_at,
            updated_at=user.created_at,
        )
        self.users[user.id] = user
        self.organizations[organization.id] = OrganizationMembership(
            organization=organization, membership=membership
        )
        return RegistrationRecord(
            user=user, organization=organization, membership=membership
        )


class MemoryOrganizations:
    def __init__(self, users: MemoryUsers) -> None:
        self._users = users

    async def get_default_for_user(self, user_id: str) -> OrganizationMembership | None:
        return next(
            (
                context
                for context in self._users.organizations.values()
                if context.membership.user_id == user_id
                and context.membership.is_active
            ),
            None,
        )

    async def get_membership(
        self, *, user_id: str, organization_id: str
    ) -> OrganizationMembership | None:
        context = self._users.organizations.get(organization_id)
        if context is None or context.membership.user_id != user_id:
            return None
        return context


class MemorySessions:
    def __init__(self) -> None:
        self.sessions: dict[str, SessionRecord] = {}
        self.reject_active_organization_update = False

    async def create(
        self,
        *,
        user_id: str,
        active_organization_id: str,
        token_hash: str,
        csrf_token_hash: str,
        expires_at: datetime,
    ) -> SessionRecord:
        session = SessionRecord(
            id=f"session-{len(self.sessions) + 1}",
            user_id=user_id,
            active_organization_id=active_organization_id,
            token_hash=token_hash,
            csrf_token_hash=csrf_token_hash,
            expires_at=expires_at,
            revoked_at=None,
            created_at=datetime.utcnow(),
        )
        self.sessions[session.id] = session
        return session

    async def get_active_by_token_hash(
        self, *, token_hash: str, now: datetime
    ) -> SessionRecord | None:
        return next(
            (
                session
                for session in self.sessions.values()
                if session.token_hash == token_hash
                and session.revoked_at is None
                and session.expires_at > now
            ),
            None,
        )

    async def revoke(self, *, session_id: str, revoked_at: datetime) -> None:
        session = self.sessions[session_id]
        self.sessions[session_id] = SessionRecord(
            id=session.id,
            user_id=session.user_id,
            active_organization_id=session.active_organization_id,
            token_hash=session.token_hash,
            csrf_token_hash=session.csrf_token_hash,
            expires_at=session.expires_at,
            revoked_at=revoked_at,
            created_at=session.created_at,
        )

    async def set_active_organization(
        self, *, session_id: str, organization_id: str, now: datetime
    ) -> bool:
        if self.reject_active_organization_update:
            return False
        session = self.sessions[session_id]
        self.sessions[session_id] = SessionRecord(
            id=session.id,
            user_id=session.user_id,
            active_organization_id=organization_id,
            token_hash=session.token_hash,
            csrf_token_hash=session.csrf_token_hash,
            expires_at=session.expires_at,
            revoked_at=session.revoked_at,
            created_at=session.created_at,
        )
        return session.revoked_at is None and session.expires_at > now


class MemoryHasher:
    def hash(self, password: str) -> str:
        return f"argon2:{password}"

    def verify(self, password: str, password_hash: str) -> bool:
        return password_hash == self.hash(password)


@pytest.mark.asyncio
async def test_register_login_and_logout_issue_and_revoke_opaque_session() -> None:
    users = MemoryUsers()
    sessions = MemorySessions()
    service = AuthService(
        users=users,
        organizations=MemoryOrganizations(users),
        sessions=sessions,
        password_hasher=MemoryHasher(),
        session_ttl=timedelta(hours=1),
    )
    now = datetime(2026, 1, 1)

    registered = await service.register(
        email=" User@Example.com ",
        password="password-1",
        display_name="  Analyst   One ",
        now=now,
    )
    assert registered.user.email == "user@example.com"
    assert registered.user.display_name == "Analyst One"
    assert users.users[registered.user.id].password_hash == "argon2:password-1"
    assert registered.session_token not in {
        record.token_hash for record in sessions.sessions.values()
    }

    logged_in = await service.login(
        email="USER@example.com", password="password-1", now=now
    )
    context = await service.authenticate(session_token=logged_in.session_token, now=now)
    assert context is not None
    assert context.user == registered.user
    assert context.membership.organization_id == registered.active_organization_id

    await service.logout(session_token=logged_in.session_token, now=now)
    assert (
        await service.authenticate(session_token=logged_in.session_token, now=now)
        is None
    )


@pytest.mark.asyncio
async def test_registration_conflict_and_invalid_login_are_safe() -> None:
    service = AuthService(
        users=(users := MemoryUsers()),
        organizations=MemoryOrganizations(users),
        sessions=MemorySessions(),
        password_hasher=MemoryHasher(),
    )
    now = datetime.utcnow()
    await service.register(
        email="user@example.com",
        password="password-1",
        display_name="User One",
        now=now,
    )
    with pytest.raises(RegistrationConflictError):
        await service.register(
            email=" USER@example.com ",
            password="password-2",
            display_name="User Two",
            now=now,
        )
    with pytest.raises(InvalidCredentialsError):
        await service.login(email="user@example.com", password="wrong-pass", now=now)


def test_session_token_and_csrf_values_are_stored_as_hashes() -> None:
    assert hash_secret("opaque-token") != "opaque-token"


@pytest.mark.asyncio
async def test_active_organization_selection_requires_active_membership() -> None:
    users = MemoryUsers()
    sessions = MemorySessions()
    service = AuthService(
        users=users,
        organizations=MemoryOrganizations(users),
        sessions=sessions,
        password_hasher=MemoryHasher(),
    )
    now = datetime(2026, 1, 1)
    registered = await service.register(
        email="owner@example.com",
        password="password-1",
        display_name="Owner One",
        now=now,
    )
    second_organization = OrganizationRecord(
        id="organization-second", name="Second", created_at=now
    )
    second_membership = MembershipRecord(
        id="membership-second",
        organization_id=second_organization.id,
        user_id=registered.user.id,
        role=MembershipRole.MEMBER,
        status=MembershipStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    users.organizations[second_organization.id] = OrganizationMembership(
        organization=second_organization, membership=second_membership
    )

    selected = await service.select_active_organization(
        session_token=registered.session_token,
        organization_id=second_organization.id,
        now=now,
    )
    assert selected.membership.id == second_membership.id
    assert selected.session.active_organization_id == second_organization.id

    users.organizations[second_organization.id] = OrganizationMembership(
        organization=second_organization,
        membership=replace(second_membership, status=MembershipStatus.SUSPENDED),
    )
    assert (
        await service.authenticate(session_token=registered.session_token, now=now)
    ) is None


@pytest.mark.asyncio
async def test_active_organization_selection_rejects_a_revocation_race() -> None:
    users = MemoryUsers()
    sessions = MemorySessions()
    sessions.reject_active_organization_update = True
    service = AuthService(
        users=users,
        organizations=MemoryOrganizations(users),
        sessions=sessions,
        password_hasher=MemoryHasher(),
    )
    now = datetime(2026, 1, 1)
    registered = await service.register(
        email="race@example.com",
        password="password-1",
        display_name="Race One",
        now=now,
    )

    with pytest.raises(InvalidOrganizationContextError, match="authentication"):
        await service.select_active_organization(
            session_token=registered.session_token,
            organization_id=registered.active_organization_id,
            now=now,
        )


@pytest.mark.asyncio
async def test_actor_authentication_survives_an_invalid_active_membership() -> None:
    users = MemoryUsers()
    sessions = MemorySessions()
    service = AuthService(
        users=users,
        organizations=MemoryOrganizations(users),
        sessions=sessions,
        password_hasher=MemoryHasher(),
    )
    now = datetime(2026, 1, 1)
    registered = await service.register(
        email="actor@example.com",
        password="password-1",
        display_name="Actor One",
        now=now,
    )
    membership = users.organizations[registered.active_organization_id].membership
    users.organizations[registered.active_organization_id] = OrganizationMembership(
        organization=users.organizations[
            registered.active_organization_id
        ].organization,
        membership=replace(membership, status=MembershipStatus.SUSPENDED),
    )

    assert (
        await service.authenticate(session_token=registered.session_token, now=now)
    ) is None
    actor = await service.authenticate_actor(
        session_token=registered.session_token, now=now
    )
    assert actor is not None
    assert actor.user.id == registered.user.id
