from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter, ValidationError

from .contracts import (
    ErrorBody,
    ErrorResponse,
    FLSInput,
    FLSResult,
    InferenceRequest,
    InferenceResponse,
    NewsInput,
    NewsResult,
)
from .errors import (
    ServiceError,
    cancelled,
    deadline_exceeded,
    inference_failed,
    invalid_argument,
    unauthenticated,
)
from .models import InferenceRunner, make_default_runners
from .runtime import OperationRuntime
from .telemetry import REQUESTS, metrics_app

_DEFAULTS = {"news.sentiment": 500, "sec.fls": 750}
_MAXIMUMS = {"news.sentiment": 1_000, "sec.fls": 1_500}
_CAPACITY = {"news.sentiment": (4, 4), "sec.fls": (2, 1)}
_IDEMPOTENCY_TTL_SECONDS = 60.0


@dataclass
class _RequestEntry:
    fingerprint: str
    task: asyncio.Task[InferenceResponse]
    waiters: int = 0
    cached_response: InferenceResponse | None = None
    expires_at: float | None = None


class RequestDeduplicator:
    def __init__(self) -> None:
        self._entries: dict[str, _RequestEntry] = {}

    async def execute(
        self,
        *,
        request_id: str,
        fingerprint: str,
        deadline_ms: int,
        operation_name: str,
        model_revision: str,
        operation: Callable[[], Awaitable[InferenceResponse]],
    ) -> InferenceResponse:
        now = asyncio.get_running_loop().time()
        self._prune(now)
        entry = self._entries.get(request_id)
        if entry is not None and entry.fingerprint != fingerprint:
            REQUESTS.labels(operation_name, model_revision, "INVALID_ARGUMENT").inc()
            raise invalid_argument("request ID was already used with different input")
        if entry is not None and entry.cached_response is None:
            if entry.task.done():
                self._complete(request_id, entry, entry.task)
                entry = self._entries.get(request_id)
            elif entry.task.cancelling():
                self._entries.pop(request_id, None)
                entry = None
        if entry is not None and entry.cached_response is not None:
            REQUESTS.labels(operation_name, model_revision, "IDEMPOTENT_REPLAY").inc()
            return entry.cached_response
        is_owner = entry is None
        if is_owner:
            task = asyncio.create_task(operation())
            entry = _RequestEntry(fingerprint=fingerprint, task=task)
            self._entries[request_id] = entry
            task.add_done_callback(
                lambda completed: self._complete(request_id, entry, completed)
            )
        entry.waiters += 1
        try:
            if is_owner:
                response = await asyncio.shield(entry.task)
            else:
                response = await asyncio.wait_for(
                    asyncio.shield(entry.task), timeout=deadline_ms / 1000.0
                )
            REQUESTS.labels(operation_name, model_revision, "SUCCESS").inc()
            return response
        except ServiceError as exc:
            REQUESTS.labels(operation_name, model_revision, exc.code).inc()
            raise
        except TimeoutError as exc:
            REQUESTS.labels(operation_name, model_revision, "DEADLINE_EXCEEDED").inc()
            raise deadline_exceeded() from exc
        except asyncio.CancelledError as exc:
            REQUESTS.labels(operation_name, model_revision, "CANCELLED").inc()
            raise cancelled() from exc
        except Exception as exc:
            REQUESTS.labels(operation_name, model_revision, "INFERENCE_FAILED").inc()
            raise inference_failed() from exc
        finally:
            entry.waiters -= 1
            if entry.waiters == 0 and not entry.task.done():
                entry.task.cancel()

    def _complete(
        self,
        request_id: str,
        entry: _RequestEntry,
        task: asyncio.Task[InferenceResponse],
    ) -> None:
        if self._entries.get(request_id) is not entry:
            return
        if task.cancelled():
            self._entries.pop(request_id, None)
            return
        try:
            response = task.result()
        except Exception:
            self._entries.pop(request_id, None)
            return
        entry.cached_response = response
        entry.expires_at = asyncio.get_running_loop().time() + _IDEMPOTENCY_TTL_SECONDS

    def _prune(self, now: float) -> None:
        expired = [
            request_id
            for request_id, entry in self._entries.items()
            if entry.expires_at is not None and entry.expires_at <= now
        ]
        for request_id in expired:
            self._entries.pop(request_id, None)


def _request_id(request: Request) -> str:
    supplied = request.headers.get("X-Request-ID", "")
    if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", supplied):
        return supplied
    return uuid4().hex


async def _wait_until_disconnected(request: Request) -> None:
    while True:
        try:
            message = await asyncio.wait_for(request.receive(), timeout=0.05)
        except TimeoutError:
            continue
        if message.get("type") == "http.disconnect":
            return


async def _await_with_disconnect(
    request: Request, operation: Awaitable[InferenceResponse]
) -> InferenceResponse:
    execution = asyncio.ensure_future(operation)
    disconnect = asyncio.create_task(_wait_until_disconnected(request))
    try:
        completed, _pending = await asyncio.wait(
            {execution, disconnect}, return_when=asyncio.FIRST_COMPLETED
        )
        if execution in completed:
            return await execution
        execution.cancel()
        await execution
        raise cancelled()
    except asyncio.CancelledError as exc:
        execution.cancel()
        raise cancelled() from exc
    finally:
        disconnect.cancel()
        if not execution.done():
            execution.cancel()
        await asyncio.gather(execution, disconnect, return_exceptions=True)


def _error_response(request: Request, error: ServiceError) -> JSONResponse:
    response = ErrorResponse(
        schema_version="inference.v1",
        request_id=_request_id(request),
        error=ErrorBody(
            code=error.code,
            message=error.message,
            retryable=error.retryable,
            retry_after_ms=error.retry_after_ms,
        ),
    )
    headers = {}
    if error.retry_after_ms is not None:
        headers["Retry-After"] = str(max(1, error.retry_after_ms // 1000))
    return JSONResponse(
        status_code=error.status_code,
        content=response.model_dump(mode="json"),
        headers=headers,
    )


def _parse_input(request: InferenceRequest) -> NewsInput | FLSInput:
    adapter = TypeAdapter(
        NewsInput if request.operation == "news.sentiment" else FLSInput
    )
    try:
        return adapter.validate_python(request.input)
    except ValidationError as exc:
        raise invalid_argument("operation input failed validation") from exc


def _authorized(request: Request, token: str) -> bool:
    if not token:
        return os.getenv("INFERENCE_ALLOW_INSECURE", "0").strip().lower() in {
            "1",
            "true",
            "yes",
        }
    return secrets.compare_digest(
        request.headers.get("Authorization", ""), f"Bearer {token}"
    )


def create_app(
    *,
    runners: Mapping[str, InferenceRunner] | None = None,
    token: str | None = None,
) -> FastAPI:
    configured_runners = make_default_runners() if runners is None else dict(runners)
    unknown_operations = configured_runners.keys() - _CAPACITY.keys()
    if unknown_operations:
        raise ValueError(
            f"unsupported inference operations: {', '.join(sorted(unknown_operations))}"
        )
    if not configured_runners:
        raise ValueError("at least one inference operation must be configured")
    service_token = (
        token if token is not None else os.getenv("INFERENCE_SERVICE_TOKEN", "")
    )
    runtimes: dict[str, OperationRuntime] = {}
    for operation, runner in configured_runners.items():
        in_flight, queue_depth = _CAPACITY[operation]
        runtimes[operation] = OperationRuntime(
            runner=runner,
            max_in_flight=in_flight,
            queue_depth=queue_depth,
        )
    request_deduplicator = RequestDeduplicator()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        insecure_allowed = os.getenv(
            "INFERENCE_ALLOW_INSECURE", "0"
        ).strip().lower() in {
            "1",
            "true",
            "yes",
        }
        if not service_token and not insecure_allowed:
            raise RuntimeError("INFERENCE_SERVICE_TOKEN must be set")
        application.state.runtimes = runtimes
        await asyncio.gather(*(runtime.start() for runtime in runtimes.values()))
        try:
            yield
        finally:
            await asyncio.gather(
                *(runtime.stop(grace_seconds=5.0) for runtime in runtimes.values())
            )

    application = FastAPI(
        title="Private Model Inference Service",
        version="1.0",
        lifespan=lifespan,
    )

    @application.exception_handler(ServiceError)
    async def handle_service_error(request: Request, exc: ServiceError) -> JSONResponse:
        return _error_response(request, exc)

    @application.exception_handler(ValidationError)
    async def handle_validation_error(
        request: Request, exc: ValidationError
    ) -> JSONResponse:
        _ = exc
        return _error_response(request, invalid_argument("request validation failed"))

    @application.get("/livez")
    async def livez() -> dict[str, str]:
        return {"status": "ok"}

    application.mount("/metrics", metrics_app())

    @application.get("/readyz")
    async def readyz() -> JSONResponse:
        states = {
            operation: {
                "ready": runtime.ready,
                "accepting": runtime.accepting,
                "queue_size": runtime.queue_size,
                "in_flight": runtime.in_flight,
                "model_revision": runtime.model_revision,
            }
            for operation, runtime in runtimes.items()
        }
        ready = all(state["ready"] and state["accepting"] for state in states.values())
        return JSONResponse(
            status_code=200 if ready else 503,
            content={"ready": ready, "operations": states},
        )

    @application.post("/v1/inference", response_model=InferenceResponse)
    async def inference(request: Request) -> InferenceResponse:
        if not _authorized(request, service_token):
            raise unauthenticated()
        request_id = _request_id(request)
        try:
            raw = await request.json()
            parsed_request = InferenceRequest.model_validate(raw)
        except (ValueError, ValidationError) as exc:
            raise invalid_argument("request validation failed") from exc
        payload = _parse_input(parsed_request)
        runtime = runtimes.get(parsed_request.operation)
        if runtime is None:
            raise invalid_argument("operation is not allowlisted")
        requested_deadline = (
            parsed_request.deadline_ms or _DEFAULTS[parsed_request.operation]
        )
        deadline_ms = min(requested_deadline, _MAXIMUMS[parsed_request.operation])
        request_payload = payload.model_dump(mode="json")
        fingerprint = hashlib.sha256(
            json.dumps(
                {"operation": parsed_request.operation, "input": request_payload},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        async def run_inference() -> InferenceResponse:
            result = await runtime.submit(
                request_payload,
                deadline_ms=deadline_ms,
                request_id=request_id,
            )
            if parsed_request.operation == "news.sentiment":
                typed_result: NewsResult | FLSResult = NewsResult.model_validate(result)
            else:
                typed_result = FLSResult.model_validate(result)
            return InferenceResponse(
                schema_version="inference.v1",
                request_id=request_id,
                operation=parsed_request.operation,
                model_revision=runtime.model_revision,
                result=typed_result,
            )

        return await _await_with_disconnect(
            request,
            request_deduplicator.execute(
                request_id=request_id,
                fingerprint=fingerprint,
                deadline_ms=deadline_ms,
                operation_name=parsed_request.operation,
                model_revision=runtime.model_revision,
                operation=run_inference,
            ),
        )

    return application


app = create_app()
