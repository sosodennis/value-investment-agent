from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from src.auth.application.errors import (
    AuthError,
    InvalidCredentialsError,
    InvalidOrganizationContextError,
    RateLimitExceeded,
    RegistrationConflictError,
)
from src.auth.application.rate_limit import rate_limiter
from src.auth.application.wiring import get_auth_service
from src.auth.domain.policies import AuthPolicyError
from src.auth.interface.contracts import (
    LoginRequest,
    Principal,
    RegisterRequest,
    SelectOrganizationRequest,
)
from src.auth.interface.dependencies import (
    clear_auth_cookies,
    require_current_actor_mutation,
    require_current_user,
    set_auth_cookies,
)
from src.shared.kernel.rate_limit import RateLimiterUnavailable

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])
SESSION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60


def _client_key(request: Request, operation: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"auth:{operation}:{host}"


@router.post("/register", response_model=Principal, status_code=201)
async def register(
    request: Request,
    response: Response,
    body: RegisterRequest,
) -> Principal:
    try:
        await rate_limiter.check(
            key=_client_key(request, "register"),
            limit=10,
            window_seconds=300,
        )
        session = await get_auth_service().register(
            email=body.email,
            password=body.password,
            display_name=body.display_name,
            now=datetime.utcnow(),
        )
    except RegistrationConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "rate_limited",
                "message": str(exc),
                "retry_after_seconds": exc.retry_after_seconds,
            },
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except RateLimiterUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "rate_limiter_unavailable"},
            headers={"Retry-After": "5"},
        ) from exc
    except AuthPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvalidOrganizationContextError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    set_auth_cookies(
        response,
        session_token=session.session_token,
        csrf_token=session.csrf_token,
        max_age=SESSION_MAX_AGE_SECONDS,
    )
    context = await get_auth_service().authenticate(
        session_token=session.session_token, now=datetime.utcnow()
    )
    if context is None:
        raise HTTPException(
            status_code=500, detail="active organization is unavailable"
        )
    return Principal.from_context(context)


@router.post("/login", response_model=Principal)
async def login(
    request: Request,
    response: Response,
    body: LoginRequest,
) -> Principal:
    try:
        await rate_limiter.check(
            key=_client_key(request, "login"),
            limit=15,
            window_seconds=300,
        )
        session = await get_auth_service().login(
            email=body.email,
            password=body.password,
            now=datetime.utcnow(),
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=401, detail="invalid email or password"
        ) from exc
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "rate_limited",
                "message": str(exc),
                "retry_after_seconds": exc.retry_after_seconds,
            },
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except RateLimiterUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "rate_limiter_unavailable"},
            headers={"Retry-After": "5"},
        ) from exc
    except AuthPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvalidOrganizationContextError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    set_auth_cookies(
        response,
        session_token=session.session_token,
        csrf_token=session.csrf_token,
        max_age=SESSION_MAX_AGE_SECONDS,
    )
    context = await get_auth_service().authenticate(
        session_token=session.session_token, now=datetime.utcnow()
    )
    if context is None:
        raise HTTPException(
            status_code=500, detail="active organization is unavailable"
        )
    return Principal.from_context(context)


@router.get("/me", response_model=Principal)
async def me(principal: Principal = Depends(require_current_user)) -> Principal:
    return principal


@router.put("/session/organization", response_model=Principal)
async def select_active_organization(
    request: Request,
    body: SelectOrganizationRequest,
    actor=Depends(require_current_actor_mutation),
) -> Principal:
    from src.audit.application.recording import record_best_effort
    from src.audit.domain.entities import AuditOutcome

    token = request.cookies.get("app_session", "")
    try:
        context = await get_auth_service().select_active_organization(
            session_token=token,
            organization_id=body.organization_id,
            now=datetime.utcnow(),
        )
    except InvalidOrganizationContextError as exc:
        current_context = await get_auth_service().authenticate(
            session_token=token, now=datetime.utcnow()
        )
        if current_context is not None:
            await record_best_effort(
                organization_id=current_context.membership.organization_id,
                actor_user_id=actor.user.id,
                action="context.organization.selection_denied",
                outcome=AuditOutcome.DENIED,
                target_type="organization",
                target_id=body.organization_id,
                correlation_id=request.headers.get("X-Request-ID"),
                payload={"requested_organization_id": body.organization_id},
            )
        raise HTTPException(
            status_code=404, detail="organization context not found"
        ) from exc
    await record_best_effort(
        organization_id=body.organization_id,
        actor_user_id=actor.user.id,
        action="context.organization.selected",
        outcome=AuditOutcome.SUCCESS,
        target_type="organization",
        target_id=body.organization_id,
        correlation_id=request.headers.get("X-Request-ID"),
    )
    return Principal.from_context(context)


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    actor=Depends(require_current_actor_mutation),
) -> None:
    from src.audit.application.recording import record_best_effort
    from src.audit.domain.entities import AuditOutcome

    token = request.cookies.get("app_session", "")
    await get_auth_service().logout(session_token=token, now=datetime.utcnow())
    await record_best_effort(
        organization_id=actor.session.active_organization_id,
        actor_user_id=actor.user.id,
        action="context.session.logged_out",
        outcome=AuditOutcome.SUCCESS,
        target_type="session",
        target_id=actor.session.id,
        correlation_id=request.headers.get("X-Request-ID"),
    )
    clear_auth_cookies(response)
