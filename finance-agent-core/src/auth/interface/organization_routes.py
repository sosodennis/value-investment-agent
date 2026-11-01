from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.auth.application.errors import (
    AuthError,
    AuthorizationDeniedError,
    InvalidMembershipTransitionError,
    MembershipInvariantError,
    MembershipNotFoundError,
    OrganizationMutationConflictError,
    OrganizationNotFoundError,
)
from src.auth.application.rate_limit import enforce_rate_limit, rate_limit_settings
from src.auth.application.wiring import (
    get_authorization_service,
    get_directory_service,
    get_organization_service,
)
from src.auth.domain.authorization import (
    AuthorizationContext,
    AuthorizationResource,
    OrganizationPermission,
)
from src.auth.domain.entities import (
    AuthenticatedActorContext,
    AuthenticatedContext,
    MembershipRole,
    MembershipStatus,
    OrganizationMember,
    OrganizationMembership,
    OrganizationRecord,
)
from src.auth.domain.policies import AuthPolicyError
from src.auth.interface.contracts import (
    DirectorySearchResponse,
    DirectoryUserResponse,
    OrganizationCreateRequest,
    OrganizationMemberResponse,
    OrganizationOwnershipTransferRequest,
    OrganizationRenameRequest,
    OrganizationResponse,
    OrganizationRoleChangeRequest,
    OrganizationStatusChangeRequest,
)
from src.auth.interface.dependencies import (
    current_actor,
    record_denied_permission,
    require_current_actor_mutation,
    require_current_context_mutation,
    require_organization_permission,
)

router = APIRouter(prefix="/api/v1/organizations", tags=["Organizations"])


def _organization_resource(
    request: Request, _context: AuthenticatedContext
) -> AuthorizationResource:
    return AuthorizationResource(organization_id=request.path_params["organization_id"])


def _member_resource(
    request: Request, context: AuthenticatedContext
) -> AuthorizationResource:
    return AuthorizationResource(
        organization_id=request.path_params["organization_id"],
        target_user_id=request.path_params.get("target_user_id", context.user.id),
    )


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
    if isinstance(
        error,
        InvalidMembershipTransitionError
        | MembershipInvariantError
        | OrganizationMutationConflictError,
    ):
        raise HTTPException(status_code=409, detail=str(error)) from error
    if isinstance(error, AuthPolicyError):
        raise HTTPException(status_code=400, detail=str(error)) from error
    raise error


@router.post(
    "", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED
)
async def create_organization(
    body: OrganizationCreateRequest,
    actor: AuthenticatedActorContext = Depends(require_current_actor_mutation),
) -> OrganizationResponse:
    try:
        organization = await get_organization_service().create_organization(
            actor=actor, name=body.name, now=datetime.utcnow()
        )
    except (AuthError, AuthPolicyError) as error:
        _raise_http(error)
    return _organization_response(organization)


@router.get("", response_model=list[OrganizationResponse])
async def list_organizations(
    actor: AuthenticatedActorContext = Depends(current_actor),
) -> list[OrganizationResponse]:
    organizations = await get_organization_service().list_organizations(actor=actor)
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
            OrganizationPermission.MEMBERSHIP_ROLE_CHANGE,
            resource_factory=_member_resource,
        )
    ),
) -> list[OrganizationMemberResponse]:
    members = await get_organization_service().list_members(
        context=context, organization_id=organization_id
    )
    return [_member_response(member) for member in members]


@router.get(
    "/{organization_id}/directory/users",
    response_model=DirectorySearchResponse,
)
async def search_directory_users(
    request: Request,
    organization_id: str,
    q: str = Query(default="", max_length=80),
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, max_length=2048),
    context: AuthenticatedContext = Depends(
        require_organization_permission(
            OrganizationPermission.DIRECTORY_SEARCH,
            resource_factory=_organization_resource,
        )
    ),
) -> DirectorySearchResponse:
    try:
        await enforce_rate_limit(
            request=request,
            organization_id=organization_id,
            actor_user_id=context.user.id,
            operation="directory.search",
            key_parts=(context.user.id, organization_id),
            limit=rate_limit_settings.directory_per_user_minute,
            window_seconds=60,
        )
        page = await get_directory_service().search_users(
            context=context,
            query=q,
            limit=limit,
            cursor=cursor,
        )
    except AuthPolicyError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return DirectorySearchResponse(
        items=[
            DirectoryUserResponse(
                user_id=item.user_id,
                display_name=item.display_name,
            )
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )


@router.patch(
    "/{organization_id}/members/{target_user_id}/role",
    response_model=OrganizationMemberResponse,
)
async def change_member_role(
    request: Request,
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
    role_resource = AuthorizationResource(
        organization_id=organization_id,
        target_user_id=target_user_id,
        requested_role=MembershipRole(body.role),
    )
    try:
        get_authorization_service().require(
            context=AuthorizationContext.from_authenticated_context(context),
            permission=OrganizationPermission.MEMBERSHIP_ROLE_CHANGE,
            resource=role_resource,
        )
    except AuthorizationDeniedError as error:
        await record_denied_permission(
            request=request,
            context=context,
            permission=OrganizationPermission.MEMBERSHIP_ROLE_CHANGE,
            resource=role_resource,
            failure_code=error.code,
        )
        _raise_http(error)
    await enforce_rate_limit(
        request=request,
        organization_id=organization_id,
        actor_user_id=context.user.id,
        operation="membership.role_change",
        key_parts=(context.user.id, organization_id),
        limit=rate_limit_settings.role_changes_per_actor_hour,
        window_seconds=3600,
    )
    await enforce_rate_limit(
        request=request,
        organization_id=organization_id,
        actor_user_id=context.user.id,
        operation="membership.role_change.organization",
        key_parts=(organization_id,),
        limit=rate_limit_settings.role_changes_per_organization_hour,
        window_seconds=3600,
    )
    try:
        member = await get_organization_service().change_role(
            context=context,
            organization_id=organization_id,
            target_user_id=target_user_id,
            requested_role=MembershipRole(body.role),
            now=datetime.utcnow(),
        )
    except (AuthError, AuthPolicyError) as error:
        if isinstance(error, AuthorizationDeniedError):
            await record_denied_permission(
                request=request,
                context=context,
                permission=OrganizationPermission.MEMBERSHIP_ROLE_CHANGE,
                resource=AuthorizationResource(
                    organization_id=organization_id, target_user_id=target_user_id
                ),
                failure_code=error.code,
            )
        _raise_http(error)
    return _member_response(member)


@router.patch(
    "/{organization_id}/members/{target_user_id}/status",
    response_model=OrganizationMemberResponse,
)
async def change_member_status(
    request: Request,
    organization_id: str,
    target_user_id: str,
    body: OrganizationStatusChangeRequest,
    context: AuthenticatedContext = Depends(
        require_organization_permission(
            OrganizationPermission.MEMBERSHIP_REMOVE,
            resource_factory=_member_resource,
            context_dependency=require_current_context_mutation,
        )
    ),
) -> OrganizationMemberResponse:
    await enforce_rate_limit(
        request=request,
        organization_id=organization_id,
        actor_user_id=context.user.id,
        operation="membership.status_change",
        key_parts=(context.user.id, organization_id),
        limit=rate_limit_settings.membership_changes_per_actor_hour,
        window_seconds=3600,
    )
    try:
        member = await get_organization_service().change_status(
            context=context,
            organization_id=organization_id,
            target_user_id=target_user_id,
            requested_status=MembershipStatus(body.status),
            now=datetime.utcnow(),
        )
    except (AuthError, AuthPolicyError) as error:
        if isinstance(error, AuthorizationDeniedError):
            await record_denied_permission(
                request=request,
                context=context,
                permission=OrganizationPermission.MEMBERSHIP_REMOVE,
                resource=AuthorizationResource(
                    organization_id=organization_id, target_user_id=target_user_id
                ),
                failure_code=error.code,
            )
        _raise_http(error)
    return _member_response(member)


@router.post(
    "/{organization_id}/ownership/transfer",
    response_model=OrganizationMemberResponse,
)
async def transfer_ownership(
    request: Request,
    organization_id: str,
    body: OrganizationOwnershipTransferRequest,
    context: AuthenticatedContext = Depends(
        require_organization_permission(
            OrganizationPermission.MEMBERSHIP_OWNER_TRANSFER,
            resource_factory=_member_resource,
            context_dependency=require_current_context_mutation,
        )
    ),
) -> OrganizationMemberResponse:
    await enforce_rate_limit(
        request=request,
        organization_id=organization_id,
        actor_user_id=context.user.id,
        operation="membership.owner_transfer",
        key_parts=(context.user.id, organization_id),
        limit=rate_limit_settings.owner_transfers_per_actor_hour,
        window_seconds=3600,
    )
    try:
        member = await get_organization_service().transfer_ownership(
            context=context,
            organization_id=organization_id,
            target_user_id=body.target_user_id,
            now=datetime.utcnow(),
        )
    except (AuthError, AuthPolicyError) as error:
        if isinstance(error, AuthorizationDeniedError):
            await record_denied_permission(
                request=request,
                context=context,
                permission=OrganizationPermission.MEMBERSHIP_OWNER_TRANSFER,
                resource=AuthorizationResource(
                    organization_id=organization_id,
                    target_user_id=body.target_user_id,
                ),
                failure_code=error.code,
            )
        _raise_http(error)
    return _member_response(member)


@router.post(
    "/{organization_id}/leave",
    response_model=OrganizationMemberResponse,
)
async def leave_organization(
    request: Request,
    organization_id: str,
    context: AuthenticatedContext = Depends(
        require_organization_permission(
            OrganizationPermission.MEMBERSHIP_LEAVE,
            resource_factory=_member_resource,
            context_dependency=require_current_context_mutation,
        )
    ),
) -> OrganizationMemberResponse:
    await enforce_rate_limit(
        request=request,
        organization_id=organization_id,
        actor_user_id=context.user.id,
        operation="membership.leave",
        key_parts=(context.user.id, organization_id),
        limit=rate_limit_settings.membership_changes_per_actor_hour,
        window_seconds=3600,
    )
    try:
        member = await get_organization_service().leave_organization(
            context=context, organization_id=organization_id, now=datetime.utcnow()
        )
    except (AuthError, AuthPolicyError) as error:
        if isinstance(error, AuthorizationDeniedError):
            await record_denied_permission(
                request=request,
                context=context,
                permission=OrganizationPermission.MEMBERSHIP_LEAVE,
                resource=AuthorizationResource(
                    organization_id=organization_id, target_user_id=context.user.id
                ),
                failure_code=error.code,
            )
        _raise_http(error)
    return _member_response(member)
