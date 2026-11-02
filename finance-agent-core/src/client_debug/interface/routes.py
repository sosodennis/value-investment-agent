from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.auth.interface.contracts import Principal
from src.client_debug.application.service import (
    ClientDebugBatchTooLargeError,
    ClientDebugDisabledError,
    ClientDebugService,
)
from src.client_debug.application.wiring import get_client_debug_service
from src.client_debug.infrastructure.runtime_buffer import (
    ClientDebugBufferFullError,
    ClientDebugCaptureConflictError,
    ClientDebugCaptureNotFoundError,
)
from src.client_debug.interface.contracts import (
    ClientDebugAcceptedResponse,
    ClientDebugBatchRequest,
    ClientDebugCaptureResponse,
)
from src.client_debug.interface.dependencies import (
    current_client_debug_mutation,
    current_client_debug_user,
)
from src.shared.kernel.correlation import current_correlation_id

router = APIRouter(prefix="/api/v1/client-debug", tags=["Client Debug"])


@router.post(
    "/events",
    response_model=ClientDebugAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        401: {"description": "Authentication is required."},
        403: {"description": "CSRF validation failed."},
        404: {"description": "Capture is disabled or not found."},
        409: {"description": "Event identity conflicts with an existing event."},
        413: {"description": "The request or batch is too large."},
        429: {"description": "The runtime capture buffer is full."},
    },
)
async def ingest_events(
    request: ClientDebugBatchRequest,
    principal: Principal = Depends(current_client_debug_mutation),
    service: ClientDebugService = Depends(get_client_debug_service),
) -> ClientDebugAcceptedResponse:
    try:
        return service.ingest(
            principal=principal,
            request=request,
            request_id=current_correlation_id(),
        )
    except ClientDebugDisabledError as error:
        raise HTTPException(status_code=404, detail="client_debug_not_found") from error
    except ClientDebugCaptureConflictError as error:
        raise HTTPException(
            status_code=409, detail="client_debug_event_conflict"
        ) from error
    except ClientDebugCaptureNotFoundError as error:
        raise HTTPException(
            status_code=404, detail="client_debug_capture_not_found"
        ) from error
    except ClientDebugBatchTooLargeError as error:
        raise HTTPException(
            status_code=413, detail="client_debug_batch_too_large"
        ) from error
    except ClientDebugBufferFullError as error:
        raise HTTPException(
            status_code=429, detail="client_debug_buffer_full"
        ) from error


@router.get(
    "/captures/{capture_id}",
    response_model=ClientDebugCaptureResponse,
    responses={
        401: {"description": "Authentication is required."},
        404: {"description": "Capture is disabled or not found."},
    },
)
async def read_capture(
    capture_id: UUID,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=200),
    principal: Principal = Depends(current_client_debug_user),
    service: ClientDebugService = Depends(get_client_debug_service),
) -> ClientDebugCaptureResponse:
    try:
        return service.read(
            principal=principal,
            capture_id=capture_id,
            after_seq=after_seq,
            limit=limit,
        )
    except ClientDebugDisabledError as error:
        raise HTTPException(status_code=404, detail="client_debug_not_found") from error
    except ClientDebugCaptureNotFoundError as error:
        raise HTTPException(
            status_code=404, detail="client_debug_capture_not_found"
        ) from error
