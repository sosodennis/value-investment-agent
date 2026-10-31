from __future__ import annotations

from datetime import datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI

from src.auth.domain.entities import (
    AuthenticatedActorContext,
    AuthenticatedContext,
    MembershipRecord,
    MembershipRole,
    MembershipStatus,
    OrganizationMembership,
    OrganizationRecord,
    SessionRecord,
    UserRecord,
)
from src.auth.interface.dependencies import (
    current_actor,
    current_context,
    require_current_actor_mutation,
)
from src.auth.interface.organization_routes import router


def _context() -> AuthenticatedContext:
    now = datetime(2026, 1, 1)
    user = UserRecord(
        id="user-owner",
        email="owner@example.test",
        password_hash="unused",
        created_at=now,
    )
    membership = MembershipRecord(
        id="membership-owner",
        organization_id="organization-a",
        user_id=user.id,
        role=MembershipRole.OWNER,
        status=MembershipStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    session = SessionRecord(
        id="session-owner",
        user_id=user.id,
        active_organization_id=membership.organization_id,
        token_hash="token",
        csrf_token_hash="csrf",
        expires_at=now + timedelta(hours=1),
        revoked_at=None,
        created_at=now,
    )
    return AuthenticatedContext(user=user, session=session, membership=membership)


class StubOrganizationService:
    def __init__(self, context: AuthenticatedContext) -> None:
        self.context = context
        self.created = 0

    async def create_organization(
        self, *, actor: AuthenticatedActorContext, name: str, now: datetime
    ) -> OrganizationMembership:
        self.created += 1
        organization = OrganizationRecord(
            id="organization-b", name=name, created_at=now
        )
        membership = MembershipRecord(
            id="membership-b",
            organization_id=organization.id,
            user_id=actor.user.id,
            role=MembershipRole.OWNER,
            status=MembershipStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        return OrganizationMembership(organization=organization, membership=membership)

    async def get_organization(
        self, *, context: AuthenticatedContext, organization_id: str
    ) -> OrganizationRecord:
        return OrganizationRecord(
            id=organization_id, name="Alpha", created_at=datetime(2026, 1, 1)
        )


@pytest.mark.asyncio
async def test_organization_routes_bind_server_context_and_support_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context()
    service = StubOrganizationService(context)
    monkeypatch.setattr(
        "src.auth.interface.organization_routes.get_organization_service",
        lambda: service,
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[current_context] = lambda: context
    app.dependency_overrides[current_actor] = lambda: AuthenticatedActorContext(
        user=context.user, session=context.session
    )
    app.dependency_overrides[require_current_actor_mutation] = (
        lambda: AuthenticatedActorContext(user=context.user, session=context.session)
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        created = await client.post("/api/v1/organizations", json={"name": "Beta"})
        same_organization = await client.get("/api/v1/organizations/organization-a")
        cross_organization = await client.get("/api/v1/organizations/organization-b")

    assert created.status_code == 201
    assert created.json()["organization_id"] == "organization-b"
    assert service.created == 1
    assert same_organization.status_code == 200
    assert cross_organization.status_code == 404
    assert cross_organization.json() == {"detail": "resource_not_found"}
