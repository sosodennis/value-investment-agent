from __future__ import annotations

from src.audit.application.wiring import get_audit_service, reset_audit_wiring
from src.audit.interface.routes import router as audit_router

__all__ = ["audit_router", "get_audit_service", "reset_audit_wiring"]
