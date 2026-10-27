from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from src.analysis_runtime.application.runtime_service import AnalysisRuntimeService
from src.analysis_runtime.domain.contracts import (
    InteractionIdentity,
    TickerSelectionResponse,
    WorkflowEvent,
    WorkflowSnapshot,
)
from src.analysis_runtime.domain.errors import (
    InteractionNotAvailableError,
    InvalidCursorError,
    InvalidInteractionResponseError,
    ReplayGapError,
    RunAlreadyActiveError,
    RunNotFoundError,
    SubscriberOverloadedError,
    ThreadNotFoundError,
)
from src.auth.entrypoint import (
    Principal,
    require_current_user,
    require_current_user_mutation,
)

router = APIRouter(prefix="/api/v1/threads", tags=["Analysis runtime"])


class WorkflowEventStreamResponse(StreamingResponse):
    media_type = "text/event-stream"


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity: InteractionIdentity
    response: TickerSelectionResponse


class RunResponse(BaseModel):
    thread_id: str
    run_id: str
    status: str = "started"


def _runtime(request: Request) -> AnalysisRuntimeService:
    service = getattr(request.app.state, "analysis_runtime", None)
    if service is None:
        raise HTTPException(status_code=503, detail="analysis runtime is unavailable")
    return service


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ThreadNotFoundError | RunNotFoundError):
        return HTTPException(status_code=404, detail=exc.code)
    if isinstance(
        exc,
        RunAlreadyActiveError
        | InteractionNotAvailableError
        | SubscriberOverloadedError,
    ):
        return HTTPException(status_code=409, detail=exc.code)
    if isinstance(exc, InvalidInteractionResponseError):
        return HTTPException(status_code=422, detail=exc.code)
    if isinstance(exc, ReplayGapError):
        return HTTPException(
            status_code=409,
            detail={"code": exc.code, "oldest_seq": exc.oldest_seq},
        )
    if isinstance(exc, InvalidCursorError):
        return HTTPException(status_code=400, detail=exc.code)
    return HTTPException(status_code=500, detail="analysis runtime failure")


@router.post("/{thread_id}/runs", response_model=RunResponse, status_code=202)
async def start_run(
    thread_id: str,
    body: RunRequest,
    request: Request,
    principal: Principal = Depends(require_current_user_mutation),
) -> RunResponse:
    try:
        run_id = await _runtime(request).start(
            principal_id=principal.user_id,
            thread_id=thread_id,
            input_data={"message": body.message},
        )
    except Exception as exc:
        raise _map_error(exc) from exc
    return RunResponse(thread_id=thread_id, run_id=run_id)


@router.post(
    "/{thread_id}/runs/{run_id}/resume",
    response_model=RunResponse,
    status_code=202,
)
async def resume_run(
    thread_id: str,
    run_id: str,
    body: ResumeRequest,
    request: Request,
    principal: Principal = Depends(require_current_user_mutation),
) -> RunResponse:
    if body.identity.thread_id != thread_id or body.identity.run_id != run_id:
        raise HTTPException(status_code=422, detail="interaction_identity_mismatch")
    try:
        resumed_run_id = await _runtime(request).resume(
            principal_id=principal.user_id,
            identity=body.identity,
            response=body.response,
        )
    except Exception as exc:
        raise _map_error(exc) from exc
    return RunResponse(thread_id=thread_id, run_id=resumed_run_id, status="resumed")


@router.post("/{thread_id}/runs/{run_id}/cancel", status_code=204)
async def cancel_run(
    thread_id: str,
    run_id: str,
    request: Request,
    principal: Principal = Depends(require_current_user_mutation),
) -> None:
    try:
        await _runtime(request).cancel(
            principal_id=principal.user_id, thread_id=thread_id, run_id=run_id
        )
    except Exception as exc:
        raise _map_error(exc) from exc


@router.get("/{thread_id}", response_model=WorkflowSnapshot)
async def thread_snapshot(
    thread_id: str,
    request: Request,
    principal: Principal = Depends(require_current_user),
):
    try:
        return (
            await _runtime(request).snapshot(
                principal_id=principal.user_id, thread_id=thread_id
            )
        ).model_dump(mode="json")
    except Exception as exc:
        raise _map_error(exc) from exc


@router.get("/{thread_id}/activities", response_model=WorkflowSnapshot)
async def activity_snapshot(
    thread_id: str,
    request: Request,
    principal: Principal = Depends(require_current_user),
    run_id: str | None = Query(default=None, min_length=1),
):
    try:
        snapshot = await _runtime(request).snapshot(
            principal_id=principal.user_id, thread_id=thread_id, run_id=run_id
        )
        return snapshot.model_dump(mode="json")
    except Exception as exc:
        raise _map_error(exc) from exc


@router.get(
    "/{thread_id}/events",
    response_class=WorkflowEventStreamResponse,
    responses={
        200: {
            "model": WorkflowEvent,
            "description": (
                "The response is a text/event-stream. Each data frame contains "
                "one workflow event envelope."
            ),
            "content": {
                "text/event-stream": {
                    "schema": {
                        "type": "string",
                        "description": "SSE frames with JSON workflow event payloads.",
                        "x-workflow-event-payload": {
                            "discriminator": {
                                "mapping": {
                                    "workflow.activity": "#/components/schemas/ActivityEvent",
                                    "workflow.interaction": "#/components/schemas/WorkflowInteractionEvent",
                                    "workflow.agent_output": "#/components/schemas/WorkflowAgentOutputEvent",
                                },
                                "propertyName": "event_name",
                            },
                            "oneOf": [
                                {"$ref": "#/components/schemas/ActivityEvent"},
                                {
                                    "$ref": "#/components/schemas/WorkflowInteractionEvent"
                                },
                                {
                                    "$ref": "#/components/schemas/WorkflowAgentOutputEvent"
                                },
                            ],
                        },
                    }
                }
            },
        }
    },
)
async def activity_events(
    thread_id: str,
    request: Request,
    principal: Principal = Depends(require_current_user),
    after_seq: int = Query(default=0, ge=0),
    run_id: str | None = Query(default=None, min_length=1),
):
    service = _runtime(request)
    try:
        if run_id is not None:
            await service.snapshot(
                principal_id=principal.user_id,
                thread_id=thread_id,
                run_id=run_id,
            )
        replay, subscriber = await service.subscribe(
            principal_id=principal.user_id,
            thread_id=thread_id,
            after_seq=after_seq,
        )
    except Exception as exc:
        raise _map_error(exc) from exc

    async def stream() -> AsyncIterator[str]:
        seen: set[str] = set()
        try:
            for event in replay.events:
                if run_id is not None and event.run_id != run_id:
                    continue
                seen.add(event.event_id)
                yield f"id: {event.seq_id}\nevent: {event.event_name}\ndata: {json.dumps(event.model_dump(mode='json'))}\n\n"
            yield ": heartbeat\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(
                        subscriber.receive(), timeout=service.heartbeat_seconds
                    )
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                if event is None:
                    yield 'event: error\ndata: {"code":"subscriber_overloaded"}\n\n'
                    break
                if run_id is not None and event.run_id != run_id:
                    continue
                if event.event_id in seen:
                    continue
                seen.add(event.event_id)
                yield f"id: {event.seq_id}\nevent: {event.event_name}\ndata: {json.dumps(event.model_dump(mode='json'))}\n\n"
        except asyncio.CancelledError:
            raise
        finally:
            await service.unsubscribe(subscriber)

    return WorkflowEventStreamResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
