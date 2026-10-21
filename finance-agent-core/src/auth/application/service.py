from __future__ import annotations

import asyncio
import hashlib
import secrets
from datetime import datetime, timedelta

from src.auth.application.errors import (
    InvalidCredentialsError,
    RegistrationConflictError,
)
from src.auth.application.ports import PasswordHasher, SessionRepository, UserRepository
from src.auth.domain.entities import AuthSession, SessionRecord, UserRecord
from src.auth.domain.policies import normalize_email, validate_password


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AuthService:
    def __init__(
        self,
        *,
        users: UserRepository,
        sessions: SessionRepository,
        password_hasher: PasswordHasher,
        session_ttl: timedelta = timedelta(days=7),
    ) -> None:
        self._users = users
        self._sessions = sessions
        self._password_hasher = password_hasher
        self._session_ttl = session_ttl

    async def register(
        self, *, email: str, password: str, now: datetime
    ) -> AuthSession:
        normalized_email = normalize_email(email)
        validate_password(password)
        if await self._users.get_by_email(normalized_email) is not None:
            raise RegistrationConflictError("email is already registered")
        password_hash = await asyncio.to_thread(self._password_hasher.hash, password)
        try:
            user = await self._users.create(
                email=normalized_email,
                password_hash=password_hash,
            )
        except RegistrationConflictError:
            raise
        return await self._issue_session(user=user, now=now)

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
        return await self._issue_session(user=user, now=now)

    async def authenticate(
        self, *, session_token: str, now: datetime
    ) -> UserRecord | None:
        session = await self.authenticate_session(session_token=session_token, now=now)
        if session is None:
            return None
        return await self.user_for_session(session)

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

    async def logout(self, *, session_token: str, now: datetime) -> None:
        if not session_token:
            return
        session = await self._sessions.get_active_by_token_hash(
            token_hash=hash_secret(session_token),
            now=now,
        )
        if session is not None:
            await self._sessions.revoke(session_id=session.id, revoked_at=now)

    async def _issue_session(self, *, user: UserRecord, now: datetime) -> AuthSession:
        session_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        expires_at = now + self._session_ttl
        await self._sessions.create(
            user_id=user.id,
            token_hash=hash_secret(session_token),
            csrf_token_hash=hash_secret(csrf_token),
            expires_at=expires_at,
        )
        return AuthSession(
            user=user,
            session_token=session_token,
            csrf_token=csrf_token,
            expires_at=expires_at,
        )
