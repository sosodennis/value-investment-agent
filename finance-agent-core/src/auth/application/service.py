from __future__ import annotations

import asyncio
import hashlib
import secrets
from dataclasses import replace
from datetime import datetime, timedelta

from src.auth.application.errors import (
    InvalidCredentialsError,
    InvalidOrganizationContextError,
    RegistrationConflictError,
)
from src.auth.application.ports import (
    OrganizationRepository,
    PasswordHasher,
    SessionRepository,
    UserRepository,
)
from src.auth.domain.entities import (
    AuthenticatedActorContext,
    AuthenticatedContext,
    AuthSession,
    SessionRecord,
    UserRecord,
)
from src.auth.domain.policies import (
    normalize_display_name,
    normalize_email,
    validate_password,
)


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AuthService:
    def __init__(
        self,
        *,
        users: UserRepository,
        organizations: OrganizationRepository,
        sessions: SessionRepository,
        password_hasher: PasswordHasher,
        session_ttl: timedelta = timedelta(days=7),
    ) -> None:
        self._users = users
        self._organizations = organizations
        self._sessions = sessions
        self._password_hasher = password_hasher
        self._session_ttl = session_ttl

    async def register(
        self, *, email: str, password: str, display_name: str, now: datetime
    ) -> AuthSession:
        normalized_email = normalize_email(email)
        validate_password(password)
        normalized_display_name = normalize_display_name(display_name)
        if await self._users.get_by_email(normalized_email) is not None:
            raise RegistrationConflictError("email is already registered")
        password_hash = await asyncio.to_thread(self._password_hasher.hash, password)
        try:
            registration = await self._users.create_with_default_organization(
                email=normalized_email,
                password_hash=password_hash,
                display_name=normalized_display_name,
                display_name_normalized=normalized_display_name.casefold(),
            )
        except RegistrationConflictError:
            raise
        return await self._issue_session(
            user=registration.user,
            active_organization_id=registration.organization.id,
            now=now,
        )

    async def login(self, *, email: str, password: str, now: datetime) -> AuthSession:
        normalized_email = normalize_email(email)
        validate_password(password)
        user = await self._users.get_by_email(normalized_email)
        valid = (
            await asyncio.to_thread(
                self._password_hasher.verify,
                password,
                user.password_hash if user else "",
            )
            if user is not None
            else False
        )
        if user is None or not valid:
            raise InvalidCredentialsError("invalid email or password")
        organization = await self._organizations.get_default_for_user(user.id)
        if organization is None or not organization.membership.is_active:
            raise InvalidOrganizationContextError("active organization is required")
        return await self._issue_session(
            user=user,
            active_organization_id=organization.organization.id,
            now=now,
        )

    async def authenticate(
        self, *, session_token: str, now: datetime
    ) -> AuthenticatedContext | None:
        session = await self.authenticate_session(session_token=session_token, now=now)
        if session is None:
            return None
        user = await self.user_for_session(session)
        if user is None:
            return None
        organization = await self._organizations.get_membership(
            user_id=user.id,
            organization_id=session.active_organization_id,
        )
        if organization is None or not organization.membership.is_active:
            return None
        return AuthenticatedContext(
            user=user,
            session=session,
            membership=organization.membership,
        )

    async def authenticate_actor(
        self, *, session_token: str, now: datetime
    ) -> AuthenticatedActorContext | None:
        session = await self.authenticate_session(session_token=session_token, now=now)
        if session is None:
            return None
        user = await self.user_for_session(session)
        if user is None:
            return None
        return AuthenticatedActorContext(user=user, session=session)

    async def authenticate_session(
        self, *, session_token: str, now: datetime
    ) -> SessionRecord | None:
        if not session_token:
            return None
        return await self._sessions.get_active_by_token_hash(
            token_hash=hash_secret(session_token), now=now
        )

    async def user_for_session(self, session: SessionRecord) -> UserRecord | None:
        return await self._users.get_by_id(session.user_id)

    async def select_active_organization(
        self,
        *,
        session_token: str,
        organization_id: str,
        now: datetime,
    ) -> AuthenticatedContext:
        session = await self.authenticate_session(session_token=session_token, now=now)
        if session is None:
            raise InvalidOrganizationContextError("authentication is required")
        user = await self.user_for_session(session)
        if user is None:
            raise InvalidOrganizationContextError("authentication is required")
        organization = await self._organizations.get_membership(
            user_id=user.id,
            organization_id=organization_id,
        )
        if organization is None or not organization.membership.is_active:
            raise InvalidOrganizationContextError("organization context not found")
        updated = await self._sessions.set_active_organization(
            session_id=session.id,
            organization_id=organization_id,
            now=now,
        )
        if not updated:
            raise InvalidOrganizationContextError("authentication is required")
        return AuthenticatedContext(
            user=user,
            session=replace(session, active_organization_id=organization_id),
            membership=organization.membership,
        )

    async def logout(self, *, session_token: str, now: datetime) -> None:
        if not session_token:
            return
        session = await self._sessions.get_active_by_token_hash(
            token_hash=hash_secret(session_token),
            now=now,
        )
        if session is not None:
            await self._sessions.revoke(session_id=session.id, revoked_at=now)

    async def _issue_session(
        self,
        *,
        user: UserRecord,
        active_organization_id: str,
        now: datetime,
    ) -> AuthSession:
        session_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        expires_at = now + self._session_ttl
        await self._sessions.create(
            user_id=user.id,
            active_organization_id=active_organization_id,
            token_hash=hash_secret(session_token),
            csrf_token_hash=hash_secret(csrf_token),
            expires_at=expires_at,
        )
        return AuthSession(
            user=user,
            session_token=session_token,
            csrf_token=csrf_token,
            expires_at=expires_at,
            active_organization_id=active_organization_id,
        )
