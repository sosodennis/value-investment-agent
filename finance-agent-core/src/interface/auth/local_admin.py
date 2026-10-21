"""Development-only local administrator session support.

This adapter is deliberately separate from the future user identity model. It
lets a loopback development deployment exercise admin-only settings without
making a static deployment token part of the browser contract.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from typing import Final

from fastapi import HTTPException, Request, Response
from itsdangerous import BadData, URLSafeTimedSerializer
from pydantic import BaseModel

LOCAL_ADMIN_COOKIE: Final[str] = "local_admin_session"
LOCAL_ADMIN_SUBJECT: Final[str] = "local-admin"
LOCAL_ADMIN_ROLE: Final[str] = "platform_admin"
LOCAL_ADMIN_MAX_AGE_SECONDS: Final[int] = 8 * 60 * 60
_EPHEMERAL_SESSION_SECRET = secrets.token_urlsafe(32)


class Principal(BaseModel):
    """The minimal identity contract shared by admin-only routes."""

    subject: str
    role: str
    auth_type: str


@dataclass(frozen=True)
class LocalAdminSettings:
    enabled: bool
    allowed_origins: frozenset[str]


def _environment() -> str:
    return os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "production")).strip().lower()


def _allowed_origins() -> frozenset[str]:
    configured = os.getenv("LOCAL_ADMIN_ALLOWED_ORIGINS", "").strip()
    values = (
        configured.split(",")
        if configured
        else [
            "http://127.0.0.1:3000",
            "http://localhost:3000",
            "http://127.0.0.1:3001",
            "http://localhost:3001",
        ]
    )
    return frozenset(value.strip().rstrip("/") for value in values if value.strip())


def settings() -> LocalAdminSettings:
    return LocalAdminSettings(
        enabled=_environment() in {"development", "dev", "test"},
        allowed_origins=_allowed_origins(),
    )


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    hostname = host.split(":", 1)[0].strip("[]").lower()
    if hostname == "localhost":
        return True
    return hostname in {"127.0.0.1", "::1"}


def _origin_is_allowed(request: Request, configured: LocalAdminSettings) -> bool:
    origin = request.headers.get("origin")
    if origin is None:
        return True
    return origin.rstrip("/") in configured.allowed_origins


def validate_local_admin_request(request: Request) -> None:
    config = settings()
    if not config.enabled:
        raise HTTPException(status_code=404, detail="local admin is disabled")
    if not _is_loopback_host(request.url.hostname):
        raise HTTPException(
            status_code=403, detail="local admin requires a loopback host"
        )
    if not _origin_is_allowed(request, config):
        raise HTTPException(status_code=403, detail="origin is not allowed")


def _serializer() -> URLSafeTimedSerializer:
    secret = os.getenv("LOCAL_ADMIN_SESSION_SECRET", "").strip()
    return URLSafeTimedSerializer(
        secret or _EPHEMERAL_SESSION_SECRET, salt="local-admin"
    )


def issue_local_admin_session(response: Response) -> Principal:
    value = _serializer().dumps(
        {
            "sub": LOCAL_ADMIN_SUBJECT,
            "role": LOCAL_ADMIN_ROLE,
            "nonce": secrets.token_urlsafe(12),
        }
    )
    response.set_cookie(
        key=LOCAL_ADMIN_COOKIE,
        value=value,
        max_age=LOCAL_ADMIN_MAX_AGE_SECONDS,
        httponly=True,
        secure=False,
        samesite="lax",
        path="/",
    )
    return Principal(
        subject=LOCAL_ADMIN_SUBJECT, role=LOCAL_ADMIN_ROLE, auth_type="local"
    )


def read_local_admin_session(request: Request) -> Principal | None:
    value = request.cookies.get(LOCAL_ADMIN_COOKIE)
    if not value:
        return None
    try:
        claims = _serializer().loads(value, max_age=LOCAL_ADMIN_MAX_AGE_SECONDS)
        if (
            claims.get("sub") != LOCAL_ADMIN_SUBJECT
            or claims.get("role") != LOCAL_ADMIN_ROLE
        ):
            return None
    except (BadData, TypeError, ValueError):
        return None
    return Principal(
        subject=LOCAL_ADMIN_SUBJECT, role=LOCAL_ADMIN_ROLE, auth_type="local"
    )


def require_local_admin(request: Request) -> Principal:
    validate_local_admin_request(request)
    principal = read_local_admin_session(request)
    if principal is None:
        raise HTTPException(status_code=401, detail="local admin session is required")
    return principal
