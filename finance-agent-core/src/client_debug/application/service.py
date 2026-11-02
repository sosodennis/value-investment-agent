from __future__ import annotations

import logging
from uuid import UUID

from src.auth.interface.contracts import Principal
from src.client_debug.config import ClientDebugSettings
from src.client_debug.infrastructure.runtime_buffer import (
    ClientDebugAppendResult,
    ClientDebugBuffer,
    ClientDebugOwner,
)
from src.client_debug.interface.contracts import (
    ClientDebugAcceptedResponse,
    ClientDebugBatchRequest,
    ClientDebugCaptureResponse,
    ClientDebugEventResponse,
)
from src.shared.kernel.tools.logger import get_logger, log_event


class ClientDebugDisabledError(RuntimeError):
    pass


class ClientDebugBatchTooLargeError(ValueError):
    pass


class ClientDebugService:
    def __init__(
        self,
        *,
        buffer: ClientDebugBuffer,
        settings: ClientDebugSettings,
        logger: logging.Logger | None = None,
    ) -> None:
        self._buffer = buffer
        self._settings = settings
        self._logger = logger or get_logger(__name__)

    def ingest(
        self,
        *,
        principal: Principal,
        request: ClientDebugBatchRequest,
        request_id: str | None,
    ) -> ClientDebugAcceptedResponse:
        self._ensure_enabled()
        if len(request.events) > self._settings.max_events_per_request:
            raise ClientDebugBatchTooLargeError(
                "client debug request contains too many events"
            )
        owner = self._owner(principal)
        result = self._buffer.append(
            owner=owner,
            capture_id=request.capture_id,
            events=tuple(request.events),
        )
        self._log_accepted(
            principal=principal,
            request=request,
            result=result,
            request_id=request_id,
        )
        return ClientDebugAcceptedResponse(
            capture_id=request.capture_id,
            accepted=len(result.accepted),
            duplicates=result.duplicates,
            dropped=result.dropped,
            dropped_rate_limited=result.dropped_rate_limited,
            dropped_capacity=result.dropped_capacity,
            request_id=request_id,
        )

    def read(
        self,
        *,
        principal: Principal,
        capture_id: UUID,
        after_seq: int,
        limit: int,
    ) -> ClientDebugCaptureResponse:
        self._ensure_enabled()
        events, next_seq, expires_at = self._buffer.read(
            owner=self._owner(principal),
            capture_id=capture_id,
            after_seq=after_seq,
            limit=limit,
        )
        return ClientDebugCaptureResponse(
            capture_id=capture_id,
            events=[
                ClientDebugEventResponse(
                    **stored.event.model_dump(),
                    received_at=stored.received_at,
                )
                for stored in events
            ],
            next_seq=next_seq,
            expires_at=expires_at,
        )

    def _ensure_enabled(self) -> None:
        if not self._settings.enabled:
            raise ClientDebugDisabledError("client debug capture is disabled")

    @staticmethod
    def _owner(principal: Principal) -> ClientDebugOwner:
        return ClientDebugOwner(
            user_id=principal.user_id,
            organization_id=principal.organization_id,
        )

    def _log_accepted(
        self,
        *,
        principal: Principal,
        request: ClientDebugBatchRequest,
        result: ClientDebugAppendResult,
        request_id: str | None,
    ) -> None:
        for stored in result.accepted:
            event = stored.event
            log_event(
                self._logger,
                event="client_debug.event",
                message="Client debug event accepted",
                fields={
                    "capture_id": str(request.capture_id),
                    "event_id": str(event.event_id),
                    "sequence": event.sequence,
                    "name": event.name,
                    "severity": event.severity,
                    "component": event.component,
                    "route": event.context.route,
                    "request_id": request_id,
                    "context": event.context.model_dump(mode="json"),
                    "details": event.details,
                    "received_at": stored.received_at.isoformat(),
                    "user_id": principal.user_id,
                    "organization_id": principal.organization_id,
                },
            )
