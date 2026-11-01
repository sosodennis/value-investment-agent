from __future__ import annotations

from src.audit.application.service import AuditService, audit_cursor_secret
from src.audit.infrastructure.repository import SqlAlchemyAuditRepository
from src.auth.application.wiring import get_authorization_service

_audit_service: AuditService | None = None


def get_audit_service() -> AuditService:
    global _audit_service
    if _audit_service is None:
        _audit_service = AuditService(
            repository=SqlAlchemyAuditRepository(),
            authorization=get_authorization_service(),
            cursor_secret=audit_cursor_secret(),
        )
    return _audit_service


def reset_audit_wiring() -> None:
    global _audit_service
    _audit_service = None
