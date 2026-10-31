from __future__ import annotations

import hmac
import os
from collections.abc import Awaitable, Callable
from datetime import datetime

from fastapi import Depends, HTTPException, Request, Response

from src.auth.application.authorization_service import AuthorizationService
from src.auth.application.errors import AuthorizationDeniedError
from src.auth.application.service import hash_secret
from src.auth.application.wiring import (
    get_auth_service,
    get_authorization_service,
)
from src.auth.domain.authorization import (
    AuthorizationContext,
    AuthorizationFailureCode,
    AuthorizationResource,
    OrganizationPermission,
)
from src.auth.domain.entities import AuthenticatedActorContext, AuthenticatedContext
from src.auth.interface.contracts import Principal

SESSION_COOKIE_NAME = "app_session"
CSRF_COOKIE_NAME = "app_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"

AuthorizationResourceFactory = Callable[
    [Request, AuthenticatedContext], AuthorizationResource
]
ContextDependency = Callable[..., Awaitable[AuthenticatedContext]]


def _is_production() -> bool:
    return os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "production")).lower() not in {
        "development",
        "dev",
        "test",
    }


def _now() -> datetime:
    return datetime.utcnow()


async def current_context(request: Request) -> AuthenticatedContext:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    context = await get_auth_service().authenticate(
        session_token=token or "", now=_now()
    )
    if context is None:
        raise HTTPException(status_code=401, detail="authentication is required")
    return context


async def current_actor(request: Request) -> AuthenticatedActorContext:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    actor = await get_auth_service().authenticate_actor(
        session_token=token or "", now=_now()
    )
    if actor is None:
        raise HTTPException(status_code=401, detail="authentication is required")
    return actor


async def current_user(request: Request) -> AuthenticatedContext:
    return await current_context(request)


def require_organization_permission(
    permission: OrganizationPermission,
    *,
    resource_factory: AuthorizationResourceFactory | None = None,
    context_dependency: ContextDependency = current_context,
) -> Callable[..., Awaitable[AuthenticatedContext]]:
    async def dependency(
        request: Request,
        context: AuthenticatedContext = Depends(context_dependency),
    ) -> AuthenticatedContext:
        resource = (
            resource_factory(request, context)
            if resource_factory is not None
            else _default_authorization_resource(permission, context)
        )
        _require_permission(
            service=get_authorization_service(),
            context=context,
            permission=permission,
            resource=resource,
        )
        return context

    return dependency


def _require_permission(
    *,
    service: AuthorizationService,
    context: AuthenticatedContext,
    permission: OrganizationPermission,
    resource: AuthorizationResource | None = None,
) -> None:
    try:
        service.require(
            context=AuthorizationContext.from_authenticated_context(context),
            permission=permission,
            resource=resource,
        )
    except AuthorizationDeniedError as exc:
        status_code = (
            404
            if exc.code == AuthorizationFailureCode.RESOURCE_NOT_FOUND.value
            else 403
        )
        raise HTTPException(status_code=status_code, detail=exc.code) from exc


def _default_authorization_resource(
    permission: OrganizationPermission, context: AuthenticatedContext
) -> AuthorizationResource:
    if permission is OrganizationPermission.ORGANIZATION_CREATE:
        return AuthorizationResource()
    return AuthorizationResource(organization_id=context.membership.organization_id)


async def require_current_user(request: Request) -> Principal:
    return Principal.from_context(await current_context(request))


def require_csrf(request: Request, *, expected_hash: str) -> None:
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    header_token = request.headers.get(CSRF_HEADER_NAME)
    if (
        not cookie_token
        or not header_token
        or not hmac.compare_digest(cookie_token, header_token)
    ):
        raise HTTPException(status_code=403, detail="csrf validation failed")
    if not session_csrf_matches(csrf_token=cookie_token, expected_hash=expected_hash):
        raise HTTPException(status_code=403, detail="csrf validation failed")


async def require_current_context_mutation(request: Request) -> AuthenticatedContext:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    service = get_auth_service()
    session = await service.authenticate_session(session_token=token or "", now=_now())
    if session is None:
        raise HTTPException(status_code=401, detail="authentication is required")
    require_csrf(request, expected_hash=session.csrf_token_hash)
    context = await service.authenticate(session_token=token or "", now=_now())
    if context is None or context.session.id != session.id:
        raise HTTPException(status_code=401, detail="authentication is required")
    return context


async def require_current_actor_mutation(
    request: Request,
) -> AuthenticatedActorContext:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    service = get_auth_service()
    session = await service.authenticate_session(session_token=token or "", now=_now())
    if session is None:
        raise HTTPException(status_code=401, detail="authentication is required")
    require_csrf(request, expected_hash=session.csrf_token_hash)
    actor = await service.authenticate_actor(session_token=token or "", now=_now())
    if actor is None or actor.session.id != session.id:
        raise HTTPException(status_code=401, detail="authentication is required")
    return actor


async def require_current_user_mutation(request: Request) -> Principal:
    context = await require_current_context_mutation(request)
    return Principal.from_context(context)


def set_auth_cookies(
    response: Response, *, session_token: str, csrf_token: str, max_age: int
) -> None:
    secure = _is_production()
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        max_age=max_age,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(key=CSRF_COOKIE_NAME, path="/")


def session_csrf_matches(*, csrf_token: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_secret(csrf_token), expected_hash)
