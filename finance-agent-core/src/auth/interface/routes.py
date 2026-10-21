from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from src.auth.application.errors import (
    AuthError,
    InvalidCredentialsError,
    RateLimitExceeded,
    RegistrationConflictError,
)
from src.auth.application.rate_limit import rate_limiter
from src.auth.application.wiring import get_auth_service
from src.auth.domain.policies import AuthPolicyError
from src.auth.interface.contracts import LoginRequest, Principal, RegisterRequest
from src.auth.interface.dependencies import (
    clear_auth_cookies,
    require_current_user,
    require_current_user_mutation,
    set_auth_cookies,
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
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
            now=datetime.utcnow(),
        )
    except RegistrationConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except AuthPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    set_auth_cookies(
        response,
        session_token=session.session_token,
        csrf_token=session.csrf_token,
        max_age=SESSION_MAX_AGE_SECONDS,
    )
    return Principal.from_user(session.user)


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
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except AuthPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    set_auth_cookies(
        response,
        session_token=session.session_token,
        csrf_token=session.csrf_token,
        max_age=SESSION_MAX_AGE_SECONDS,
    )
    return Principal.from_user(session.user)


@router.get("/me", response_model=Principal)
async def me(principal: Principal = Depends(require_current_user)) -> Principal:
    return principal


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    _principal: Principal = Depends(require_current_user_mutation),
) -> None:
    token = request.cookies.get("app_session", "")
    await get_auth_service().logout(session_token=token, now=datetime.utcnow())
    clear_auth_cookies(response)
