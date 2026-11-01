from __future__ import annotations

from fastapi import Depends, HTTPException

from src.auth.application.authorization_service import AuthorizationService
from src.auth.application.errors import AuthorizationDeniedError
from src.auth.application.wiring import get_authorization_service
from src.auth.domain.authorization import (
    AuthorizationContext,
    AuthorizationResource,
    OrganizationPermission,
)
from src.auth.domain.entities import AuthenticatedActorContext
from src.auth.interface.dependencies import (
    current_actor,
    require_current_actor_mutation,
)


def _require_recipient_permission(
    *, actor: AuthenticatedActorContext, service: AuthorizationService
) -> AuthenticatedActorContext:
    try:
        service.require(
            context=AuthorizationContext.from_actor_context(actor),
            permission=OrganizationPermission.NOTIFICATION_INBOX_READ,
            resource=AuthorizationResource(recipient_user_id=actor.user.id),
        )
    except AuthorizationDeniedError as error:
        raise HTTPException(status_code=403, detail=error.code) from error
    return actor


async def current_notification_recipient(
    actor: AuthenticatedActorContext = Depends(current_actor),
    service: AuthorizationService = Depends(get_authorization_service),
) -> AuthenticatedActorContext:
    return _require_recipient_permission(actor=actor, service=service)


async def current_notification_recipient_mutation(
    actor: AuthenticatedActorContext = Depends(require_current_actor_mutation),
    service: AuthorizationService = Depends(get_authorization_service),
) -> AuthenticatedActorContext:
    try:
        service.require(
            context=AuthorizationContext.from_actor_context(actor),
            permission=OrganizationPermission.NOTIFICATION_INBOX_MUTATE,
            resource=AuthorizationResource(recipient_user_id=actor.user.id),
        )
    except AuthorizationDeniedError as error:
        raise HTTPException(status_code=403, detail=error.code) from error
    return actor
