from __future__ import annotations

import hmac
import os
from datetime import datetime

from fastapi import HTTPException, Request, Response

from src.auth.application.service import hash_secret
from src.auth.application.wiring import get_auth_service
from src.auth.domain.entities import UserRecord
from src.auth.interface.contracts import Principal

SESSION_COOKIE_NAME = "app_session"
CSRF_COOKIE_NAME = "app_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"


def _is_production() -> bool:
    return os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "production")).lower() not in {
        "development",
        "dev",
        "test",
    }


def _now() -> datetime:
    return datetime.utcnow()


async def current_user(request: Request) -> UserRecord:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user = await get_auth_service().authenticate(session_token=token or "", now=_now())
    if user is None:
        raise HTTPException(status_code=401, detail="authentication is required")
    return user


async def require_current_user(request: Request) -> Principal:
    return Principal.from_user(await current_user(request))


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


async def require_current_user_mutation(request: Request) -> Principal:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    service = get_auth_service()
    session = await service.authenticate_session(session_token=token or "", now=_now())
    if session is None:
        raise HTTPException(status_code=401, detail="authentication is required")
    require_csrf(request, expected_hash=session.csrf_token_hash)
    user = await service.user_for_session(session)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication is required")
    return Principal.from_user(user)


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
