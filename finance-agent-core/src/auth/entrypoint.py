from __future__ import annotations

from src.auth.application.wiring import get_auth_service, get_ownership_service
from src.auth.interface.contracts import Principal
from src.auth.interface.dependencies import (
    clear_auth_cookies,
    require_current_user,
    require_current_user_mutation,
    set_auth_cookies,
)
from src.auth.interface.routes import router as auth_router

__all__ = [
    "Principal",
    "auth_router",
    "clear_auth_cookies",
    "get_auth_service",
    "get_ownership_service",
    "require_current_user",
    "require_current_user_mutation",
    "set_auth_cookies",
]
