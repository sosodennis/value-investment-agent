from __future__ import annotations

from datetime import datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from src.auth.application.rate_limit import rate_limiter
from src.auth.domain.entities import (
    AuthenticatedContext,
    DirectoryPage,
    DirectoryUser,
    MembershipRecord,
    MembershipRole,
    MembershipStatus,
    SessionRecord,
    UserRecord,
)
from src.auth.interface.dependencies import current_context
from src.auth.interface.organization_routes import router


def _context(*, organization_id: str = "organization-a") -> AuthenticatedContext:
    now = datetime(2026, 1, 1)
    user = UserRecord(
        id="actor-directory",
        email="actor@example.test",
        password_hash="unused",
        created_at=now,
        display_name="Actor",
    )
    membership = MembershipRecord(
        id="membership-directory",
        organization_id=organization_id,
        user_id=user.id,
        role=MembershipRole.MEMBER,
        status=MembershipStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    return AuthenticatedContext(
        user=user,
        membership=membership,
        session=SessionRecord(
            id="session-directory",
            user_id=user.id,
            active_organization_id=organization_id,
            token_hash="token",
            csrf_token_hash="csrf",
            expires_at=now + timedelta(hours=1),
            revoked_at=None,
            created_at=now,
        ),
    )


class StubDirectoryService:
    async def search_users(self, *, context, query, limit, cursor):
        return DirectoryPage(
            items=(DirectoryUser(user_id="opaque-target", display_name="Target User"),),
            next_cursor="next-page",
        )


class InvalidCursorDirectoryService:
    async def search_users(self, *, context, query, limit, cursor):
        from src.auth.domain.policies import AuthPolicyError

        raise AuthPolicyError("invalid directory cursor")


@pytest.mark.asyncio
async def test_directory_route_returns_only_minimal_opaque_recipient_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[current_context] = lambda: context
    service = StubDirectoryService()
    monkeypatch.setattr(
        "src.auth.interface.organization_routes.get_directory_service",
        lambda: service,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            "/api/v1/organizations/organization-a/directory/users",
            params={"q": "target", "limit": 10},
        )

    assert response.status_code == 200
    assert response.json() == {
        "items": [{"user_id": "opaque-target", "display_name": "Target User"}],
        "next_cursor": "next-page",
    }
    assert "email" not in response.text


@pytest.mark.asyncio
async def test_directory_route_rejects_a_foreign_organization_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[current_context] = lambda: _context()
    monkeypatch.setattr(
        "src.auth.interface.organization_routes.get_directory_service",
        StubDirectoryService,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            "/api/v1/organizations/organization-b/directory/users",
            params={"q": "target"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "resource_not_found"}


@pytest.mark.asyncio
async def test_directory_rate_limit_is_actor_and_organization_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[current_context] = lambda: context
    monkeypatch.setattr(
        "src.auth.interface.organization_routes.get_directory_service",
        StubDirectoryService,
    )

    async def limited(*, key: str, limit: int, window_seconds: int) -> None:
        from src.auth.application.errors import RateLimitExceeded

        raise RateLimitExceeded("too many attempts; try again later")

    monkeypatch.setattr(rate_limiter, "check", limited)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            "/api/v1/organizations/organization-a/directory/users",
            params={"q": "target"},
        )

    assert response.status_code == 429


@pytest.mark.asyncio
async def test_directory_route_requires_authentication() -> None:
    app = FastAPI()
    app.include_router(router)

    def unauthenticated() -> AuthenticatedContext:
        raise HTTPException(status_code=401, detail="authentication is required")

    app.dependency_overrides[current_context] = unauthenticated
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            "/api/v1/organizations/organization-a/directory/users",
            params={"q": "target"},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_directory_route_exposes_invalid_cursor_as_a_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[current_context] = lambda: _context()
    monkeypatch.setattr(
        "src.auth.interface.organization_routes.get_directory_service",
        InvalidCursorDirectoryService,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            "/api/v1/organizations/organization-a/directory/users",
            params={"q": "target", "cursor": "bad"},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "invalid directory cursor"}
