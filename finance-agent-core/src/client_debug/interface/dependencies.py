from __future__ import annotations

from fastapi import HTTPException, Request

from src.auth.interface.contracts import Principal
from src.auth.interface.dependencies import (
    require_current_user,
    require_current_user_mutation,
)
from src.client_debug.config import ClientDebugSettings


def _ensure_enabled() -> None:
    if not ClientDebugSettings.from_environment().enabled:
        raise HTTPException(status_code=404, detail="client_debug_not_found")


async def current_client_debug_user(request: Request) -> Principal:
    _ensure_enabled()
    return await require_current_user(request)


async def current_client_debug_mutation(request: Request) -> Principal:
    _ensure_enabled()
    return await require_current_user_mutation(request)
