from __future__ import annotations

from datetime import datetime, timedelta

import httpx
import pytest
from fastapi import Depends, FastAPI, Request

from src.auth.application.authorization_service import AuthorizationService
from src.auth.application.errors import AuthorizationDeniedError
from src.auth.domain.authorization import (
    ROLE_PERMISSION_MATRIX,
    AuthorizationContext,
    AuthorizationFailureCode,
    AuthorizationResource,
    OrganizationAuthorizationPolicy,
    OrganizationPermission,
)
from src.auth.domain.entities import (
    AuthenticatedContext,
    MembershipRecord,
    MembershipRole,
    MembershipStatus,
    SessionRecord,
    UserRecord,
)
from src.auth.interface.dependencies import (
    current_context,
    require_organization_permission,
)


def _authorization_context(
    role: MembershipRole,
    *,
    user_id: str = "actor",
    organization_id: str | None = "organization-a",
    status: MembershipStatus = MembershipStatus.ACTIVE,
) -> AuthorizationContext:
    return AuthorizationContext(
        actor_user_id=user_id,
        organization_id=organization_id,
        membership_id="membership-a" if organization_id else None,
        role=role,
        membership_status=status,
    )


def _resource_for(permission: OrganizationPermission) -> AuthorizationResource:
    if permission is OrganizationPermission.ORGANIZATION_CREATE:
        return AuthorizationResource()
    if permission in {
        OrganizationPermission.NOTIFICATION_INBOX_READ,
        OrganizationPermission.NOTIFICATION_INBOX_MUTATE,
    }:
        return AuthorizationResource(recipient_user_id="actor")
    if permission is OrganizationPermission.INVITATION_READ:
        return AuthorizationResource(
            organization_id="organization-a", recipient_user_id="recipient"
        )
    if permission is OrganizationPermission.MEMBERSHIP_REMOVE:
        return AuthorizationResource(
            organization_id="organization-a",
            target_user_id="target",
            target_role=MembershipRole.MEMBER,
        )
    if permission is OrganizationPermission.MEMBERSHIP_LEAVE:
        return AuthorizationResource(
            organization_id="organization-a", target_user_id="actor", owner_count=2
        )
    if permission is OrganizationPermission.MEMBERSHIP_ROLE_CHANGE:
        return AuthorizationResource(
            organization_id="organization-a",
            target_user_id="target",
            target_role=MembershipRole.MEMBER,
            requested_role=MembershipRole.MEMBER,
            owner_count=2,
        )
    if permission is OrganizationPermission.MEMBERSHIP_OWNER_TRANSFER:
        return AuthorizationResource(
            organization_id="organization-a",
            target_user_id="target",
            target_role=MembershipRole.MEMBER,
            requested_role=MembershipRole.OWNER,
            owner_count=1,
        )
    if permission is OrganizationPermission.INVITATION_CREATE:
        return AuthorizationResource(
            organization_id="organization-a", requested_role=MembershipRole.MEMBER
        )
    return AuthorizationResource(organization_id="organization-a")


@pytest.mark.parametrize("role", list(MembershipRole))
@pytest.mark.parametrize("permission", list(OrganizationPermission))
def test_permission_matrix_has_an_explicit_decision(
    role: MembershipRole, permission: OrganizationPermission
) -> None:
    decision = OrganizationAuthorizationPolicy.evaluate(
        context=_authorization_context(role),
        permission=permission,
        resource=_resource_for(permission),
    )
    expected = permission in ROLE_PERMISSION_MATRIX[role]
    assert decision.allowed is expected


def test_cross_organization_resources_are_indistinguishable_from_missing() -> None:
    decision = OrganizationAuthorizationPolicy.evaluate(
        context=_authorization_context(MembershipRole.ADMIN),
        permission=OrganizationPermission.PROVIDER_CONFIG_READ,
        resource=AuthorizationResource(organization_id="organization-b"),
    )
    assert decision.allowed is False
    assert decision.failure_code is AuthorizationFailureCode.RESOURCE_NOT_FOUND


def test_inactive_membership_cannot_authorize_organization_actions() -> None:
    decision = OrganizationAuthorizationPolicy.evaluate(
        context=_authorization_context(
            MembershipRole.OWNER, status=MembershipStatus.SUSPENDED
        ),
        permission=OrganizationPermission.ORGANIZATION_READ,
        resource=AuthorizationResource(organization_id="organization-a"),
    )
    assert (
        decision.failure_code is AuthorizationFailureCode.ORGANIZATION_CONTEXT_REQUIRED
    )


@pytest.mark.parametrize(
    ("role", "requested_role", "allowed"),
    [
        (MembershipRole.OWNER, MembershipRole.ADMIN, True),
        (MembershipRole.OWNER, MembershipRole.MEMBER, True),
        (MembershipRole.OWNER, MembershipRole.OWNER, False),
        (MembershipRole.ADMIN, MembershipRole.MEMBER, True),
        (MembershipRole.ADMIN, MembershipRole.ADMIN, False),
        (MembershipRole.ADMIN, MembershipRole.OWNER, False),
        (MembershipRole.MEMBER, MembershipRole.MEMBER, False),
    ],
)
def test_invitation_role_authority(
    role: MembershipRole, requested_role: MembershipRole, allowed: bool
) -> None:
    decision = OrganizationAuthorizationPolicy.evaluate(
        context=_authorization_context(role),
        permission=OrganizationPermission.INVITATION_CREATE,
        resource=AuthorizationResource(
            organization_id="organization-a", requested_role=requested_role
        ),
    )
    assert decision.allowed is allowed
    if not allowed:
        assert decision.failure_code in {
            AuthorizationFailureCode.PERMISSION_DENIED,
            AuthorizationFailureCode.ROLE_TRANSITION_NOT_ALLOWED,
        }


def test_invitation_read_is_private_to_recipients_for_members() -> None:
    non_recipient = OrganizationAuthorizationPolicy.evaluate(
        context=_authorization_context(MembershipRole.MEMBER),
        permission=OrganizationPermission.INVITATION_READ,
        resource=AuthorizationResource(
            organization_id="organization-a", recipient_user_id="recipient"
        ),
    )
    recipient = OrganizationAuthorizationPolicy.evaluate(
        context=_authorization_context(MembershipRole.MEMBER, organization_id=None),
        permission=OrganizationPermission.INVITATION_READ,
        resource=AuthorizationResource(recipient_user_id="actor"),
    )
    assert non_recipient.failure_code is AuthorizationFailureCode.PERMISSION_DENIED
    assert recipient.allowed is True


def test_last_owner_and_self_removal_rules_are_denied() -> None:
    last_owner = OrganizationAuthorizationPolicy.evaluate(
        context=_authorization_context(MembershipRole.ADMIN),
        permission=OrganizationPermission.MEMBERSHIP_REMOVE,
        resource=AuthorizationResource(
            organization_id="organization-a",
            target_user_id="target",
            target_role=MembershipRole.OWNER,
            owner_count=1,
        ),
    )
    self_leave = OrganizationAuthorizationPolicy.evaluate(
        context=_authorization_context(MembershipRole.OWNER),
        permission=OrganizationPermission.MEMBERSHIP_LEAVE,
        resource=AuthorizationResource(
            organization_id="organization-a", target_user_id="actor", owner_count=1
        ),
    )
    self_remove = OrganizationAuthorizationPolicy.evaluate(
        context=_authorization_context(MembershipRole.ADMIN),
        permission=OrganizationPermission.MEMBERSHIP_REMOVE,
        resource=AuthorizationResource(
            organization_id="organization-a", target_user_id="actor", owner_count=2
        ),
    )
    assert last_owner.failure_code is AuthorizationFailureCode.LAST_OWNER_PROTECTED
    assert self_leave.failure_code is AuthorizationFailureCode.LAST_OWNER_PROTECTED
    assert self_remove.failure_code is AuthorizationFailureCode.SELF_REMOVAL_NOT_ALLOWED


def test_role_change_cannot_assign_owner_or_demote_the_last_owner() -> None:
    assign_owner = OrganizationAuthorizationPolicy.evaluate(
        context=_authorization_context(MembershipRole.OWNER),
        permission=OrganizationPermission.MEMBERSHIP_ROLE_CHANGE,
        resource=AuthorizationResource(
            organization_id="organization-a",
            target_user_id="target",
            target_role=MembershipRole.MEMBER,
            requested_role=MembershipRole.OWNER,
            owner_count=1,
        ),
    )
    demote_last_owner = OrganizationAuthorizationPolicy.evaluate(
        context=_authorization_context(MembershipRole.OWNER),
        permission=OrganizationPermission.MEMBERSHIP_ROLE_CHANGE,
        resource=AuthorizationResource(
            organization_id="organization-a",
            target_user_id="target",
            target_role=MembershipRole.OWNER,
            requested_role=MembershipRole.MEMBER,
            owner_count=1,
        ),
    )
    assert (
        assign_owner.failure_code
        is AuthorizationFailureCode.ROLE_TRANSITION_NOT_ALLOWED
    )
    assert (
        demote_last_owner.failure_code is AuthorizationFailureCode.LAST_OWNER_PROTECTED
    )


def test_authorization_service_raises_stable_failure_code() -> None:
    service = AuthorizationService()
    with pytest.raises(AuthorizationDeniedError) as raised:
        service.require(
            context=_authorization_context(MembershipRole.MEMBER),
            permission=OrganizationPermission.PROVIDER_CONFIG_WRITE,
            resource=AuthorizationResource(organization_id="organization-a"),
        )
    assert raised.value.code == AuthorizationFailureCode.PERMISSION_DENIED.value


def _authenticated_context(role: MembershipRole) -> AuthenticatedContext:
    now = datetime.utcnow()
    user = UserRecord(
        id="actor",
        email="actor@example.test",
        password_hash="unused",
        created_at=now,
        display_name="Actor",
    )
    membership = MembershipRecord(
        id="membership-a",
        organization_id="organization-a",
        user_id="actor",
        role=role,
        status=MembershipStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    session = SessionRecord(
        id="session-a",
        user_id="actor",
        active_organization_id="organization-a",
        token_hash="token",
        csrf_token_hash="csrf",
        expires_at=now + timedelta(hours=1),
        revoked_at=None,
        created_at=now,
    )
    return AuthenticatedContext(user=user, session=session, membership=membership)


@pytest.mark.asyncio
async def test_permission_dependency_enforces_policy_at_http_boundary() -> None:
    app = FastAPI()

    @app.get("/provider")
    async def provider_route(
        _context: AuthenticatedContext = Depends(
            require_organization_permission(
                OrganizationPermission.PROVIDER_CONFIG_WRITE
            )
        ),
    ) -> dict[str, bool]:
        return {"ok": True}

    app.dependency_overrides[current_context] = lambda: _authenticated_context(
        MembershipRole.MEMBER
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        denied = await client.get("/provider")
    assert denied.status_code == 403
    assert denied.json() == {"detail": "permission_denied"}

    app.dependency_overrides[current_context] = lambda: _authenticated_context(
        MembershipRole.OWNER
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        allowed = await client.get("/provider")
    assert allowed.status_code == 200
    assert allowed.json() == {"ok": True}


@pytest.mark.asyncio
async def test_permission_dependency_binds_route_resource_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    denied_events: list[dict[str, object]] = []

    async def capture_denied_event(**kwargs: object) -> None:
        denied_events.append(kwargs)

    monkeypatch.setattr(
        "src.audit.application.recording.record_best_effort", capture_denied_event
    )

    def resource_from_path(
        request: Request, _context: AuthenticatedContext
    ) -> AuthorizationResource:
        return AuthorizationResource(
            organization_id=request.path_params["organization_id"]
        )

    @app.get("/organizations/{organization_id}/provider")
    async def provider_route(
        _context: AuthenticatedContext = Depends(
            require_organization_permission(
                OrganizationPermission.PROVIDER_CONFIG_READ,
                resource_factory=resource_from_path,
            )
        ),
    ) -> dict[str, bool]:
        return {"ok": True}

    app.dependency_overrides[current_context] = lambda: _authenticated_context(
        MembershipRole.OWNER
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        same_organization = await client.get("/organizations/organization-a/provider")
        cross_organization = await client.get("/organizations/organization-b/provider")
    assert same_organization.status_code == 200
    assert cross_organization.status_code == 404
    assert cross_organization.json() == {"detail": "resource_not_found"}
    assert denied_events[-1]["organization_id"] == "organization-a"
    assert denied_events[-1]["target_id"] == "organization-b"


@pytest.mark.asyncio
async def test_permission_dependency_supports_authenticated_organization_creation() -> (
    None
):
    app = FastAPI()

    @app.post("/organizations", status_code=201)
    async def create_organization(
        _context: AuthenticatedContext = Depends(
            require_organization_permission(OrganizationPermission.ORGANIZATION_CREATE)
        ),
    ) -> dict[str, bool]:
        return {"created": True}

    app.dependency_overrides[current_context] = lambda: _authenticated_context(
        MembershipRole.MEMBER
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        created = await client.post("/organizations")
    assert created.status_code == 201
    assert created.json() == {"created": True}
