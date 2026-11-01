from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from src.audit.application.service import AuditCursorError, AuditService
from src.audit.application.wiring import get_audit_service
from src.audit.domain.entities import AuditEvent
from src.auth.application.errors import AuthorizationDeniedError
from src.auth.domain.entities import AuthenticatedContext

from .contracts import AuditEventListResponse, AuditEventResponse
from .dependencies import current_audit_reader

router = APIRouter(prefix="/api/v1/organizations", tags=["Organization Audit"])


def _response(event: AuditEvent) -> AuditEventResponse:
    return AuditEventResponse(
        event_id=event.id,
        organization_id=event.organization_id,
        actor_type=event.actor_type.value,
        actor_user_id=event.actor_user_id,
        actor_system=event.actor_system,
        action=event.action,
        target_type=event.target_type,
        target_id=event.target_id,
        outcome=event.outcome.value,
        correlation_id=event.correlation_id,
        payload=event.payload,
        occurred_at=event.occurred_at,
    )


@router.get(
    "/{organization_id}/audit-events",
    response_model=AuditEventListResponse,
    responses={
        400: {"description": "Malformed or tampered pagination cursor"},
        403: {"description": "The actor lacks organization.audit.read"},
        404: {"description": "The organization is outside the verified context"},
    },
)
async def list_audit_events(
    organization_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(
        default=None,
        max_length=512,
        description="Opaque signed cursor for occurred_at DESC, id DESC pagination.",
    ),
    context: AuthenticatedContext = current_audit_reader,
    service: AuditService = Depends(get_audit_service),
) -> AuditEventListResponse:
    try:
        result = await service.list_for_context(
            context=context,
            organization_id=organization_id,
            limit=limit,
            cursor=cursor,
        )
    except AuditCursorError as error:
        raise HTTPException(status_code=400, detail="invalid_audit_cursor") from error
    except AuthorizationDeniedError as error:
        status_code = 404 if error.code == "resource_not_found" else 403
        raise HTTPException(status_code=status_code, detail=error.code) from error
    return AuditEventListResponse(
        items=[_response(item) for item in result.items],
        next_cursor=result.next_cursor,
    )
