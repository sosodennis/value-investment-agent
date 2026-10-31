from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.auth.application.errors import (
    AuthError,
    AuthorizationDeniedError,
    InvalidMembershipTransitionError,
    MembershipInvariantError,
    MembershipNotFoundError,
    OrganizationNotFoundError,
)
from src.auth.application.wiring import get_organization_service
from src.auth.domain.authorization import AuthorizationResource, OrganizationPermission
from src.auth.domain.entities import (
    AuthenticatedContext,
    MembershipRole,
    MembershipStatus,
    OrganizationMember,
    OrganizationMembership,
    OrganizationRecord,
)
from src.auth.domain.policies import AuthPolicyError
from src.auth.interface.contracts import (
    OrganizationCreateRequest,
    OrganizationMemberResponse,
    OrganizationOwnershipTransferRequest,
    OrganizationRenameRequest,
    OrganizationResponse,
    OrganizationRoleChangeRequest,
    OrganizationStatusChangeRequest,
)
from src.auth.interface.dependencies import (
    current_context,
    require_current_context_mutation,
    require_organization_permission,
)

router = APIRouter(prefix="/api/v1/organizations", tags=["Organizations"])


def _organization_resource(
    request: Request, _context: AuthenticatedContext
) -> AuthorizationResource:
    return AuthorizationResource(organization_id=request.path_params["organization_id"])


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _organization_response(
    membership: OrganizationMembership,
) -> OrganizationResponse:
    return OrganizationResponse(
        organization_id=membership.organization.id,
        name=membership.organization.name,
        created_at=_utc(membership.organization.created_at),
        membership_id=membership.membership.id,
        role=membership.membership.role.value,
        status=membership.membership.status.value,
    )


def _organization_detail_response(
    organization: OrganizationRecord, context: AuthenticatedContext
) -> OrganizationResponse:
    return OrganizationResponse(
        organization_id=organization.id,
        name=organization.name,
        created_at=_utc(organization.created_at),
        membership_id=context.membership.id,
        role=context.membership.role.value,
        status=context.membership.status.value,
    )


def _member_response(member: OrganizationMember) -> OrganizationMemberResponse:
    return OrganizationMemberResponse(
        user_id=member.user.id,
        email=member.user.email,
        membership_id=member.membership.id,
        organization_id=member.membership.organization_id,
        role=member.membership.role.value,
        status=member.membership.status.value,
        created_at=_utc(member.membership.created_at),
        updated_at=_utc(member.membership.updated_at),
    )


def _raise_http(error: Exception) -> None:
    if isinstance(error, AuthorizationDeniedError):
        code = error.code
        raise HTTPException(
            status_code=404 if code == "resource_not_found" else 403,
            detail=code,
        ) from error
    if isinstance(error, OrganizationNotFoundError | MembershipNotFoundError):
        raise HTTPException(status_code=404, detail="not_found") from error
    if isinstance(error, InvalidMembershipTransitionError | MembershipInvariantError):
        raise HTTPException(status_code=409, detail=str(error)) from error
    if isinstance(error, AuthPolicyError):
        raise HTTPException(status_code=400, detail=str(error)) from error
    raise error


@router.post(
    "", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED
)
async def create_organization(
    body: OrganizationCreateRequest,
    context: AuthenticatedContext = Depends(
        require_organization_permission(
            OrganizationPermission.ORGANIZATION_CREATE,
            context_dependency=require_current_context_mutation,
        )
    ),
) -> OrganizationResponse:
    try:
        organization = await get_organization_service().create_organization(
            context=context, name=body.name, now=datetime.utcnow()
        )
    except (AuthError, AuthPolicyError) as error:
        _raise_http(error)
    return _organization_response(organization)


@router.get("", response_model=list[OrganizationResponse])
async def list_organizations(
    context: AuthenticatedContext = Depends(current_context),
) -> list[OrganizationResponse]:
    organizations = await get_organization_service().list_organizations(context=context)
    return [_organization_response(item) for item in organizations]


@router.get(
    "/{organization_id}",
    response_model=OrganizationResponse,
)
async def get_organization(
    organization_id: str,
    context: AuthenticatedContext = Depends(
        require_organization_permission(
            OrganizationPermission.ORGANIZATION_READ,
            resource_factory=_organization_resource,
        )
    ),
) -> OrganizationResponse:
    try:
        organization = await get_organization_service().get_organization(
            context=context, organization_id=organization_id
        )
    except (AuthError, AuthPolicyError) as error:
        _raise_http(error)
    return _organization_detail_response(organization, context)


@router.patch(
    "/{organization_id}",
    response_model=OrganizationResponse,
)
async def rename_organization(
    organization_id: str,
    body: OrganizationRenameRequest,
    context: AuthenticatedContext = Depends(
        require_organization_permission(
            OrganizationPermission.ORGANIZATION_UPDATE,
            resource_factory=_organization_resource,
            context_dependency=require_current_context_mutation,
        )
    ),
) -> OrganizationResponse:
    try:
        organization = await get_organization_service().rename_organization(
            context=context,
            organization_id=organization_id,
            name=body.name,
            now=datetime.utcnow(),
        )
    except (AuthError, AuthPolicyError) as error:
        _raise_http(error)
    return _organization_detail_response(organization, context)


@router.get(
    "/{organization_id}/members",
    response_model=list[OrganizationMemberResponse],
)
async def list_members(
    organization_id: str,
    context: AuthenticatedContext = Depends(
        require_organization_permission(
            OrganizationPermission.MEMBERSHIP_READ,
            resource_factory=_organization_resource,
        )
    ),
) -> list[OrganizationMemberResponse]:
    members = await get_organization_service().list_members(
        context=context, organization_id=organization_id
    )
    return [_member_response(member) for member in members]


@router.patch(
    "/{organization_id}/members/{target_user_id}/role",
    response_model=OrganizationMemberResponse,
)
async def change_member_role(
    organization_id: str,
    target_user_id: str,
    body: OrganizationRoleChangeRequest,
    context: AuthenticatedContext = Depends(
        require_organization_permission(
            OrganizationPermission.MEMBERSHIP_READ,
            resource_factory=_organization_resource,
            context_dependency=require_current_context_mutation,
        )
    ),
) -> OrganizationMemberResponse:
    try:
        member = await get_organization_service().change_role(
            context=context,
            organization_id=organization_id,
            target_user_id=target_user_id,
            requested_role=MembershipRole(body.role),
            now=datetime.utcnow(),
        )
    except (AuthError, AuthPolicyError) as error:
        _raise_http(error)
    return _member_response(member)


@router.patch(
    "/{organization_id}/members/{target_user_id}/status",
    response_model=OrganizationMemberResponse,
)
async def change_member_status(
    organization_id: str,
    target_user_id: str,
    body: OrganizationStatusChangeRequest,
    context: AuthenticatedContext = Depends(
        require_organization_permission(
            OrganizationPermission.MEMBERSHIP_READ,
            resource_factory=_organization_resource,
            context_dependency=require_current_context_mutation,
        )
    ),
) -> OrganizationMemberResponse:
    try:
        member = await get_organization_service().change_status(
            context=context,
            organization_id=organization_id,
            target_user_id=target_user_id,
            requested_status=MembershipStatus(body.status),
            now=datetime.utcnow(),
        )
    except (AuthError, AuthPolicyError) as error:
        _raise_http(error)
    return _member_response(member)


@router.post(
    "/{organization_id}/ownership/transfer",
    response_model=OrganizationMemberResponse,
)
async def transfer_ownership(
    organization_id: str,
    body: OrganizationOwnershipTransferRequest,
    context: AuthenticatedContext = Depends(
        require_organization_permission(
            OrganizationPermission.MEMBERSHIP_READ,
            resource_factory=_organization_resource,
            context_dependency=require_current_context_mutation,
        )
    ),
) -> OrganizationMemberResponse:
    try:
        member = await get_organization_service().transfer_ownership(
            context=context,
            organization_id=organization_id,
            target_user_id=body.target_user_id,
            now=datetime.utcnow(),
        )
    except (AuthError, AuthPolicyError) as error:
        _raise_http(error)
    return _member_response(member)


@router.post(
    "/{organization_id}/leave",
    response_model=OrganizationMemberResponse,
)
async def leave_organization(
    organization_id: str,
    context: AuthenticatedContext = Depends(
        require_organization_permission(
            OrganizationPermission.MEMBERSHIP_READ,
            resource_factory=_organization_resource,
            context_dependency=require_current_context_mutation,
        )
    ),
) -> OrganizationMemberResponse:
    try:
        member = await get_organization_service().leave_organization(
            context=context, organization_id=organization_id, now=datetime.utcnow()
        )
    except (AuthError, AuthPolicyError) as error:
        _raise_http(error)
    return _member_response(member)
