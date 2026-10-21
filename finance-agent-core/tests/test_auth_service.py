from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.auth.application.errors import (
    InvalidCredentialsError,
    RegistrationConflictError,
)
from src.auth.application.service import AuthService, hash_secret
from src.auth.domain.entities import SessionRecord, UserRecord


class MemoryUsers:
    def __init__(self) -> None:
        self.users: dict[str, UserRecord] = {}

    async def get_by_email(self, email: str) -> UserRecord | None:
        return next((user for user in self.users.values() if user.email == email), None)

    async def get_by_id(self, user_id: str) -> UserRecord | None:
        return self.users.get(user_id)

    async def create(self, *, email: str, password_hash: str) -> UserRecord:
        user = UserRecord(
            id=f"user-{len(self.users) + 1}",
            email=email,
            password_hash=password_hash,
            created_at=datetime.utcnow(),
        )
        self.users[user.id] = user
        return user


class MemorySessions:
    def __init__(self) -> None:
        self.sessions: dict[str, SessionRecord] = {}

    async def create(
        self,
        *,
        user_id: str,
        token_hash: str,
        csrf_token_hash: str,
        expires_at: datetime,
    ) -> SessionRecord:
        session = SessionRecord(
            id=f"session-{len(self.sessions) + 1}",
            user_id=user_id,
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
            token_hash=session.token_hash,
            csrf_token_hash=session.csrf_token_hash,
            expires_at=session.expires_at,
            revoked_at=revoked_at,
            created_at=session.created_at,
        )


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
        sessions=sessions,
        password_hasher=MemoryHasher(),
        session_ttl=timedelta(hours=1),
    )
    now = datetime(2026, 1, 1)

    registered = await service.register(
        email=" User@Example.com ", password="password-1", now=now
    )
    assert registered.user.email == "user@example.com"
    assert users.users[registered.user.id].password_hash == "argon2:password-1"
    assert registered.session_token not in {
        record.token_hash for record in sessions.sessions.values()
    }

    logged_in = await service.login(
        email="USER@example.com", password="password-1", now=now
    )
    assert (
        await service.authenticate(session_token=logged_in.session_token, now=now)
    ) == registered.user

    await service.logout(session_token=logged_in.session_token, now=now)
    assert (
        await service.authenticate(session_token=logged_in.session_token, now=now)
        is None
    )


@pytest.mark.asyncio
async def test_registration_conflict_and_invalid_login_are_safe() -> None:
    service = AuthService(
        users=MemoryUsers(),
        sessions=MemorySessions(),
        password_hasher=MemoryHasher(),
    )
    now = datetime.utcnow()
    await service.register(email="user@example.com", password="password-1", now=now)
    with pytest.raises(RegistrationConflictError):
        await service.register(
            email=" USER@example.com ", password="password-2", now=now
        )
    with pytest.raises(InvalidCredentialsError):
        await service.login(email="user@example.com", password="wrong-pass", now=now)


def test_session_token_and_csrf_values_are_stored_as_hashes() -> None:
    assert hash_secret("opaque-token") != "opaque-token"
