from __future__ import annotations

import logging
from datetime import UTC, datetime

from src.audit.application.wiring import get_audit_service
from src.audit.domain.entities import AuditEventDraft, AuditOutcome

logger = logging.getLogger(__name__)


async def record_best_effort(
    *,
    organization_id: str,
    actor_user_id: str | None = None,
    actor_system: str | None = None,
    action: str,
    outcome: AuditOutcome,
    target_type: str | None = None,
    target_id: str | None = None,
    payload: dict[str, object] | None = None,
    correlation_id: str | None = None,
) -> None:
    """Record a cross-service event without leaking provider operation secrets.

    Provider and notification calls can complete outside the auth transaction.
    Their audit write is therefore best-effort and must never copy credentials
    into the payload or turn a completed remote operation into a false failure.
    """

    try:
        await get_audit_service().append(
            event=AuditEventDraft(
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                actor_system=actor_system,
                action=action,
                outcome=outcome,
                target_type=target_type,
                target_id=target_id,
                payload=payload or {},
                correlation_id=correlation_id,
                occurred_at=datetime.now(UTC),
            )
        )
    except Exception:
        # The remote operation already committed; application telemetry owns
        # the alert for an unavailable audit store.
        logger.exception(
            "audit event could not be persisted action=%s organization_id=%s",
            action,
            organization_id,
        )
        return
