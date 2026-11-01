from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from src.auth.application.errors import AuthorizationDeniedError
from src.auth.application.invitation_errors import (
    InvitationConflictError,
    InvitationNotFoundError,
    InvitationValidationError,
)
from src.auth.application.invitation_service import InvitationService
from src.auth.application.rate_limit import enforce_rate_limit, rate_limit_settings
from src.auth.application.wiring import get_invitation_service
from src.auth.domain.authorization import AuthorizationResource, OrganizationPermission
from src.auth.domain.entities import (
    AuthenticatedActorContext,
    AuthenticatedContext,
    MembershipRole,
)
from src.auth.domain.invitations import InvitationOperation, InvitationRecord
from src.auth.interface.contracts import InvitationCreateRequest, InvitationResponse
from src.auth.interface.dependencies import (
    current_actor,
    record_denied_permission,
    require_current_actor_mutation,
    require_current_context_mutation,
    require_organization_permission,
)
from src.shared.kernel.rate_limit import RateLimiterUnavailable, RateLimitExceeded

router = APIRouter(prefix="/api/v1/organizations", tags=["Invitations"])


def _resource(
    request: Request, _context: AuthenticatedContext
) -> AuthorizationResource:
    return AuthorizationResource(organization_id=request.path_params["organization_id"])


def _response(invitation: InvitationRecord) -> InvitationResponse:
    return InvitationResponse(
        invitation_id=invitation.id,
        organization_id=invitation.organization_id,
        organization_name=invitation.organization_name,
        inviter_user_id=invitation.inviter_user_id,
        inviter_display_name=invitation.inviter_display_name,
        recipient_user_id=invitation.recipient_user_id,
        recipient_display_name=invitation.recipient_display_name,
        requested_role=invitation.requested_role,  # type: ignore[arg-type]
        status=invitation.status.value,  # type: ignore[arg-type]
        created_at=_utc(invitation.created_at),
        updated_at=_utc(invitation.updated_at),
        expires_at=_utc(invitation.expires_at),
        revision=invitation.revision,
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _raise_http(error: Exception) -> None:
    if isinstance(error, AuthorizationDeniedError):
        raise HTTPException(
            status_code=404 if error.code == "resource_not_found" else 403,
            detail=error.code,
        ) from error
    if isinstance(error, InvitationNotFoundError):
        raise HTTPException(status_code=404, detail="invitation_not_found") from error
    if isinstance(error, InvitationConflictError):
        raise HTTPException(status_code=409, detail=error.code) from error
    if isinstance(error, InvitationValidationError):
        raise HTTPException(status_code=400, detail=str(error)) from error
    if isinstance(error, RateLimitExceeded):
        raise HTTPException(
            status_code=429,
            detail={
                "code": "rate_limited",
                "message": str(error),
                "retry_after_seconds": error.retry_after_seconds,
            },
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from error
    if isinstance(error, RateLimiterUnavailable):
        raise HTTPException(
            status_code=503,
            detail={"code": "rate_limiter_unavailable"},
            headers={"Retry-After": "5"},
        ) from error
    raise error


@router.post(
    "/{organization_id}/invitations",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(
    request: Request,
    organization_id: str,
    body: InvitationCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_current_context_mutation),
    service: InvitationService = Depends(get_invitation_service),
) -> InvitationResponse:
    await enforce_rate_limit(
        request=request,
        organization_id=organization_id,
        actor_user_id=context.user.id,
        operation="invitation.create.actor",
        key_parts=(context.user.id, organization_id),
        limit=rate_limit_settings.invitations_per_actor_hour,
        window_seconds=3600,
    )
    await enforce_rate_limit(
        request=request,
        organization_id=organization_id,
        actor_user_id=context.user.id,
        operation="invitation.create.organization",
        key_parts=(organization_id,),
        limit=rate_limit_settings.invitations_per_organization_hour,
        window_seconds=3600,
    )
    await enforce_rate_limit(
        request=request,
        organization_id=organization_id,
        actor_user_id=context.user.id,
        operation="invitation.create.recipient",
        key_parts=(body.recipient_user_id,),
        limit=rate_limit_settings.invitations_per_recipient_hour,
        window_seconds=3600,
    )
    try:
        invitation = await service.create(
            context=context,
            organization_id=organization_id,
            recipient_user_id=body.recipient_user_id,
            requested_role=MembershipRole(body.role),
            idempotency_key=idempotency_key or "",
            now=datetime.now(UTC),
        )
    except (
        AuthorizationDeniedError,
        InvitationConflictError,
        InvitationNotFoundError,
        InvitationValidationError,
        RateLimitExceeded,
        RateLimiterUnavailable,
    ) as error:
        if isinstance(error, AuthorizationDeniedError):
            await record_denied_permission(
                request=request,
                context=context,
                permission=OrganizationPermission.INVITATION_CREATE,
                resource=AuthorizationResource(organization_id=organization_id),
                failure_code=error.code,
            )
        _raise_http(error)
    return _response(invitation)


@router.get(
    "/{organization_id}/invitations",
    response_model=list[InvitationResponse],
)
async def list_invitations(
    organization_id: str,
    context: AuthenticatedContext = Depends(
        require_organization_permission(
            OrganizationPermission.INVITATION_READ,
            resource_factory=_resource,
        )
    ),
    service: InvitationService = Depends(get_invitation_service),
) -> list[InvitationResponse]:
    try:
        invitations = await service.list_for_organization(
            context=context, organization_id=organization_id, now=datetime.now(UTC)
        )
    except (
        AuthorizationDeniedError,
        InvitationConflictError,
        InvitationNotFoundError,
        InvitationValidationError,
        RateLimitExceeded,
        RateLimiterUnavailable,
    ) as error:
        _raise_http(error)
    return [_response(invitation) for invitation in invitations]


@router.get(
    "/{organization_id}/invitations/{invitation_id}",
    response_model=InvitationResponse,
)
async def get_invitation(
    organization_id: str,
    invitation_id: str,
    actor: AuthenticatedActorContext = Depends(current_actor),
    service: InvitationService = Depends(get_invitation_service),
) -> InvitationResponse:
    try:
        invitation = await service.get_for_actor(
            actor=actor,
            organization_id=organization_id,
            invitation_id=invitation_id,
            now=datetime.now(UTC),
        )
    except InvitationNotFoundError as error:
        _raise_http(error)
    return _response(invitation)


@router.post(
    "/{organization_id}/invitations/{invitation_id}/accept",
    response_model=InvitationResponse,
)
async def accept_invitation(
    request: Request,
    organization_id: str,
    invitation_id: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: AuthenticatedActorContext = Depends(require_current_actor_mutation),
    service: InvitationService = Depends(get_invitation_service),
) -> InvitationResponse:
    await enforce_rate_limit(
        request=request,
        organization_id=organization_id,
        actor_user_id=actor.user.id,
        operation="invitation.respond",
        key_parts=(actor.user.id, organization_id),
        limit=rate_limit_settings.invitation_responses_per_recipient_hour,
        window_seconds=3600,
    )
    try:
        invitation = await service.transition_for_recipient(
            actor=actor,
            organization_id=organization_id,
            invitation_id=invitation_id,
            operation=InvitationOperation.ACCEPT,
            idempotency_key=idempotency_key or "",
            now=datetime.now(UTC),
        )
    except (
        AuthorizationDeniedError,
        InvitationConflictError,
        InvitationNotFoundError,
        InvitationValidationError,
    ) as error:
        _raise_http(error)
    return _response(invitation)


@router.post(
    "/{organization_id}/invitations/{invitation_id}/decline",
    response_model=InvitationResponse,
)
async def decline_invitation(
    request: Request,
    organization_id: str,
    invitation_id: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: AuthenticatedActorContext = Depends(require_current_actor_mutation),
    service: InvitationService = Depends(get_invitation_service),
) -> InvitationResponse:
    await enforce_rate_limit(
        request=request,
        organization_id=organization_id,
        actor_user_id=actor.user.id,
        operation="invitation.respond",
        key_parts=(actor.user.id, organization_id),
        limit=rate_limit_settings.invitation_responses_per_recipient_hour,
        window_seconds=3600,
    )
    try:
        invitation = await service.transition_for_recipient(
            actor=actor,
            organization_id=organization_id,
            invitation_id=invitation_id,
            operation=InvitationOperation.DECLINE,
            idempotency_key=idempotency_key or "",
            now=datetime.now(UTC),
        )
    except (
        AuthorizationDeniedError,
        InvitationConflictError,
        InvitationNotFoundError,
        InvitationValidationError,
    ) as error:
        _raise_http(error)
    return _response(invitation)


@router.post(
    "/{organization_id}/invitations/{invitation_id}/revoke",
    response_model=InvitationResponse,
)
async def revoke_invitation(
    request: Request,
    organization_id: str,
    invitation_id: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(
        require_organization_permission(
            OrganizationPermission.INVITATION_REVOKE,
            resource_factory=_resource,
            context_dependency=require_current_context_mutation,
        )
    ),
    service: InvitationService = Depends(get_invitation_service),
) -> InvitationResponse:
    await enforce_rate_limit(
        request=request,
        organization_id=organization_id,
        actor_user_id=context.user.id,
        operation="invitation.revoke",
        key_parts=(context.user.id, organization_id),
        limit=rate_limit_settings.invitations_per_actor_hour,
        window_seconds=3600,
    )
    try:
        invitation = await service.transition_for_manager(
            context=context,
            organization_id=organization_id,
            invitation_id=invitation_id,
            operation=InvitationOperation.REVOKE,
            idempotency_key=idempotency_key or "",
            now=datetime.now(UTC),
        )
    except (
        AuthorizationDeniedError,
        InvitationConflictError,
        InvitationNotFoundError,
        InvitationValidationError,
    ) as error:
        if isinstance(error, AuthorizationDeniedError):
            await record_denied_permission(
                request=request,
                context=context,
                permission=OrganizationPermission.INVITATION_REVOKE,
                resource=AuthorizationResource(organization_id=organization_id),
                failure_code=error.code,
            )
        _raise_http(error)
    return _response(invitation)


@router.post(
    "/{organization_id}/invitations/{invitation_id}/resend",
    response_model=InvitationResponse,
)
async def resend_invitation(
    request: Request,
    organization_id: str,
    invitation_id: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(
        require_organization_permission(
            OrganizationPermission.INVITATION_REVOKE,
            resource_factory=_resource,
            context_dependency=require_current_context_mutation,
        )
    ),
    service: InvitationService = Depends(get_invitation_service),
) -> InvitationResponse:
    await enforce_rate_limit(
        request=request,
        organization_id=organization_id,
        actor_user_id=context.user.id,
        operation="invitation.resend.actor",
        key_parts=(context.user.id, organization_id),
        limit=rate_limit_settings.invitations_per_actor_hour,
        window_seconds=3600,
    )
    await enforce_rate_limit(
        request=request,
        organization_id=organization_id,
        actor_user_id=context.user.id,
        operation="invitation.resend.invitation",
        key_parts=(invitation_id,),
        limit=rate_limit_settings.resend_per_invitation_hour,
        window_seconds=3600,
    )
    try:
        invitation = await service.transition_for_manager(
            context=context,
            organization_id=organization_id,
            invitation_id=invitation_id,
            operation=InvitationOperation.RESEND,
            idempotency_key=idempotency_key or "",
            now=datetime.now(UTC),
        )
    except (
        AuthorizationDeniedError,
        InvitationConflictError,
        InvitationNotFoundError,
        InvitationValidationError,
        RateLimitExceeded,
        RateLimiterUnavailable,
    ) as error:
        if isinstance(error, AuthorizationDeniedError):
            await record_denied_permission(
                request=request,
                context=context,
                permission=OrganizationPermission.INVITATION_REVOKE,
                resource=AuthorizationResource(organization_id=organization_id),
                failure_code=error.code,
            )
        _raise_http(error)
    return _response(invitation)
