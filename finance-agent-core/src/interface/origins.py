"""Resolve the browser origins trusted by the application."""

from __future__ import annotations

import os

_DEFAULT_FRONTEND_ORIGINS = (
    "http://127.0.0.1:3000",
    "http://localhost:3000",
    "http://127.0.0.1:3001",
    "http://localhost:3001",
)


def frontend_origins() -> tuple[str, ...]:
    configured = (
        os.getenv("FRONTEND_ALLOWED_ORIGINS", "").strip()
        or os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
        or os.getenv("LOCAL_ADMIN_ALLOWED_ORIGINS", "").strip()
    )
    if not configured:
        return _DEFAULT_FRONTEND_ORIGINS
    return tuple(
        origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()
    )
