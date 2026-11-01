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
    OrganizationMember,
    OrganizationMembership,
    OrganizationRecord,
    SessionRecord,
    UserRecord,
)
from src.auth.interface.dependencies import (
    current_actor,
    current_context,
    require_current_actor_mutation,
    require_current_context_mutation,
)
from src.auth.interface.organization_routes import router


def _context() -> AuthenticatedContext:
    now = datetime(2026, 1, 1)
    user = UserRecord(
        id="user-owner",
        email="owner@example.test",
        password_hash="unused",
        created_at=now,
        display_name="Owner",
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
        self.changed_roles: list[tuple[str, MembershipRole]] = []
        self.transferred_to: list[str] = []

    async def list_members(
        self, *, context: AuthenticatedContext, organization_id: str
    ) -> list[OrganizationMember]:
        return [
            OrganizationMember(
                user=context.user,
                membership=context.membership,
            )
        ]

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

    async def change_role(
        self,
        *,
        context: AuthenticatedContext,
        organization_id: str,
        target_user_id: str,
        requested_role: MembershipRole,
        now: datetime,
    ) -> OrganizationMember:
        self.changed_roles.append((target_user_id, requested_role))
        target = UserRecord(
            id=target_user_id,
            email="member@example.test",
            password_hash="unused",
            created_at=now,
            display_name="Member",
        )
        membership = MembershipRecord(
            id="membership-member",
            organization_id=organization_id,
            user_id=target_user_id,
            role=requested_role,
            status=MembershipStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        return OrganizationMember(user=target, membership=membership)

    async def transfer_ownership(
        self,
        *,
        context: AuthenticatedContext,
        organization_id: str,
        target_user_id: str,
        now: datetime,
    ) -> OrganizationMember:
        self.transferred_to.append(target_user_id)
        target = UserRecord(
            id=target_user_id,
            email="member@example.test",
            password_hash="unused",
            created_at=now,
            display_name="Member",
        )
        membership = MembershipRecord(
            id="membership-member",
            organization_id=organization_id,
            user_id=target_user_id,
            role=MembershipRole.OWNER,
            status=MembershipStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        return OrganizationMember(user=target, membership=membership)


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
    app.dependency_overrides[require_current_context_mutation] = lambda: context
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
        members = await client.get("/api/v1/organizations/organization-a/members")
        cross_organization = await client.get("/api/v1/organizations/organization-b")
        role_change = await client.patch(
            "/api/v1/organizations/organization-a/members/user-member/role",
            json={"role": "admin"},
        )
        ownership_transfer = await client.post(
            "/api/v1/organizations/organization-a/ownership/transfer",
            json={"target_user_id": "user-member"},
        )

    assert created.status_code == 201
    assert created.json()["organization_id"] == "organization-b"
    assert service.created == 1
    assert same_organization.status_code == 200
    assert members.status_code == 200
    assert members.json()[0]["user_id"] == "user-owner"
    assert cross_organization.status_code == 404
    assert cross_organization.json() == {"detail": "resource_not_found"}
    assert role_change.status_code == 200
    assert role_change.json()["role"] == "admin"
    assert service.changed_roles == [("user-member", MembershipRole.ADMIN)]
    assert ownership_transfer.status_code == 200
    assert ownership_transfer.json()["role"] == "owner"
    assert service.transferred_to == ["user-member"]
