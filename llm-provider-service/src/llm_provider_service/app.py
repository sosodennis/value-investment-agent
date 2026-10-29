from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from contextvars import Token
from datetime import UTC, datetime
from typing import cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError, create_model

from src.llm_provider_service.application.context import (
    reset_provider_principal,
    set_provider_principal,
)
from src.llm_provider_service.application.wiring import ProviderRuntime
from src.llm_provider_service.contracts import (
    LLM_SERVICE_CONTRACT_VERSION,
    CompletionInput,
    ErrorBody,
    ErrorResponse,
    KeyCreateInput,
    KeyDeleteResult,
    KeyIdInput,
    KeyListResult,
    KeyMutationResult,
    KeyReplaceInput,
    KeySummary,
    KeyTestResult,
    ModelSummary,
    SettingsResult,
    SettingsUpdateInput,
    SuccessResponse,
)
from src.llm_provider_service.domain.contracts import (
    CompletionRequest,
    CompletionResult,
    LLMProviderError,
    ProviderPrincipal,
    StructuredRequest,
)
from src.llm_provider_service.domain.errors import ProviderSettingsError
from src.llm_provider_service.domain.provider_models import ManagedProviderKey
from src.llm_provider_service.domain.routes import DEFAULT_MODEL_ALIAS
from src.shared.internal_services import (
    INTERNAL_CONTRACT_VERSION,
    InternalAuthenticationError,
    InternalContextValidationError,
    InternalRequestContext,
    authenticate_internal_request,
)

_PROVIDER_KEY_ERROR_STATUSES = {
    "not_found": 404,
    "invalid_key": 400,
    "invalid_key_id": 400,
    "model_not_free": 400,
    "request_rejected": 400,
    "replacement_must_differ": 400,
    "already_owned": 409,
    "replacement_in_progress": 409,
    "rate_limited": 429,
}


def _token() -> str | None:
    return os.getenv("LLM_PROVIDER_SERVICE_TOKEN") or None


def _remaining(deadline: datetime) -> float:
    return (deadline - datetime.now(UTC)).total_seconds()


async def _authorized_body(
    request: Request,
) -> tuple[InternalRequestContext, dict[str, object]]:
    raw = TypeAdapter(dict[str, object]).validate_json(await request.body())
    raw_context = raw.get("context", {})
    context = authenticate_internal_request(
        request.headers.get("Authorization"),
        expected_token=_token(),
        raw_context=raw_context if isinstance(raw_context, dict) else {},
    )
    if _remaining(context.deadline_at) <= 0:
        raise TimeoutError("request deadline expired")
    operation = TypeAdapter(dict[str, object]).validate_python(raw.get("input", {}))
    return context, operation


def _success(
    context: InternalRequestContext, result: dict[str, object]
) -> dict[str, object]:
    response = SuccessResponse(
        correlation_id=context.correlation_id,
        contract_version=INTERNAL_CONTRACT_VERSION,
        schema_version=LLM_SERVICE_CONTRACT_VERSION,
        result=result,
    )
    return response.model_dump(mode="json")


def _error(
    correlation_id: str,
    code: str,
    message: str,
    status: int,
    *,
    retryable: bool = False,
    retry_after_ms: int | None = None,
) -> JSONResponse:
    response = ErrorResponse(
        correlation_id=correlation_id,
        contract_version=INTERNAL_CONTRACT_VERSION,
        error=ErrorBody(
            code=code,
            message=message,
            retryable=retryable,
            retry_after_ms=retry_after_ms,
        ),
    )
    return JSONResponse(status_code=status, content=response.model_dump(mode="json"))


def _summary(key: ManagedProviderKey) -> KeySummary:
    return KeySummary(
        id=key.id,
        label=key.label,
        suffix=key.suffix,
        fingerprint=key.fingerprint,
        created_at=key.created_at,
        status=key.status,
        last_tested_at=key.last_tested_at,
        failure_count=key.failure_count,
        cooldown_until=key.cooldown_until,
        last_error=key.last_error,
        last_used_at=key.last_used_at,
        replacement_retire_at=key.replacement_retire_at,
    )


def _deadline_timeout(context: InternalRequestContext, requested: float) -> float:
    remaining = _remaining(context.deadline_at)
    if remaining <= 0:
        raise TimeoutError("request deadline expired")
    return min(requested, remaining)


def _response_model(schema: dict[str, object]) -> type[BaseModel]:
    properties = schema.get("properties", {})
    fields: dict[str, tuple[type[object], None]] = (
        {name: (object, None) for name in properties if isinstance(name, str)}
        if isinstance(properties, dict)
        else {}
    )

    class StructuredResponse(BaseModel):
        model_config = ConfigDict(extra="allow")

        @classmethod
        def model_json_schema(
            cls, *_args: object, **_kwargs: object
        ) -> dict[str, object]:
            return schema

    dynamic_create_model = cast(Callable[..., object], create_model)
    return cast(
        type[BaseModel],
        dynamic_create_model(
            str(schema.get("title", "StructuredResponse")),
            __base__=StructuredResponse,
            **fields,
        ),
    )


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    runtime = ProviderRuntime()
    application.state.runtime = runtime
    cleanup_task: asyncio.Task[None] | None = None
    try:
        await runtime.start()
        try:
            await runtime.synchronize_model()
        except Exception as exc:
            logger.warning(
                "LLM selected model synchronization failed (%s)",
                type(exc).__name__,
            )
        cleanup_task = asyncio.create_task(_replacement_cleanup_loop(runtime))
        yield
    finally:
        if cleanup_task is not None:
            cleanup_task.cancel()
            await asyncio.gather(cleanup_task, return_exceptions=True)
        await runtime.close()


app = FastAPI(title="Private LLM Provider Service", version="1.0", lifespan=lifespan)
logger = logging.getLogger(__name__)


async def _replacement_cleanup_loop(runtime: ProviderRuntime) -> None:
    while True:
        try:
            deleted = await runtime.cleanup_replacements()
            if deleted:
                logger.info("Expired LLM key replacements removed: %s", deleted)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "LLM key replacement cleanup failed (%s)", type(exc).__name__
            )
        await asyncio.sleep(60)


@app.get("/livez")
async def livez() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    runtime: ProviderRuntime = request.app.state.runtime
    status = "ready" if runtime.ready and _token() else "not_ready"
    return JSONResponse(
        status_code=200 if status == "ready" else 503,
        content={"status": status, "contract_version": INTERNAL_CONTRACT_VERSION},
    )


def _bind_principal(
    context: InternalRequestContext,
) -> Token[ProviderPrincipal | None]:
    return set_provider_principal(
        ProviderPrincipal(user_id=context.principal.subject_id)
    )


@app.post("/v1/completions")
async def completion(request: Request) -> JSONResponse:
    correlation_id = "unknown"
    try:
        context, raw_input = await _authorized_body(request)
        correlation_id = context.correlation_id
        payload = CompletionInput.model_validate(raw_input)
        if payload.route.alias != DEFAULT_MODEL_ALIAS:
            return _error(
                correlation_id, "policy_rejected", "provider route is not allowed", 400
            )
        runtime: ProviderRuntime = request.app.state.runtime
        if not runtime.ready or runtime.gateway is None:
            return _error(
                correlation_id,
                "not_ready",
                "provider service is not ready",
                503,
                retryable=True,
            )
        timeout = _deadline_timeout(context, payload.timeout_seconds)
        operation = CompletionRequest(
            messages=payload.messages,
            route=payload.route,
            request_id=payload.request_id,
            operation=payload.operation,
            request_class=payload.request_class,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
            timeout_seconds=timeout,
            idempotency_key=payload.idempotency_key,
            metadata=payload.metadata,
            tools=payload.tools,
            tool_choice=payload.tool_choice,
        )
        principal_token = _bind_principal(context)
        try:
            async with asyncio.timeout(timeout):
                if payload.response_schema is None:
                    result = await runtime.gateway.acomplete(operation)
                else:
                    response_schema = _response_model(payload.response_schema)
                    structured = await runtime.gateway.acomplete_structured(
                        StructuredRequest[BaseModel](
                            completion=operation, response_schema=response_schema
                        )
                    )
                    result = CompletionResult(
                        request_id=payload.request_id,
                        text=json.dumps(
                            structured.model_dump(mode="json"), separators=(",", ":")
                        ),
                        model=payload.route.alias,
                    )
        finally:
            reset_provider_principal(principal_token)
        return JSONResponse(content=_success(context, result.model_dump(mode="json")))
    except InternalAuthenticationError as exc:
        return _error(correlation_id, exc.code, str(exc), 401)
    except (InternalContextValidationError, ValidationError):
        return _error(
            correlation_id, "invalid_context", "request context is invalid", 400
        )
    except TimeoutError:
        return _error(
            correlation_id,
            "deadline_exceeded",
            "request deadline expired",
            504,
            retryable=True,
        )
    except LLMProviderError as exc:
        return _error(
            correlation_id,
            exc.code.value,
            "LLM provider request failed",
            502,
            retryable=exc.retryable,
        )
    except Exception:
        return _error(
            correlation_id,
            "unavailable",
            "LLM provider is unavailable",
            503,
            retryable=True,
        )


@app.post("/v1/completions/stream", response_model=None)
async def stream_completion(request: Request) -> JSONResponse | StreamingResponse:
    correlation_id = "unknown"
    try:
        context, raw_input = await _authorized_body(request)
        correlation_id = context.correlation_id
        payload = CompletionInput.model_validate(raw_input)
        if payload.response_schema is not None:
            return _error(
                correlation_id,
                "invalid_argument",
                "structured streaming is unsupported",
                400,
            )
        if payload.route.alias != DEFAULT_MODEL_ALIAS:
            return _error(
                correlation_id, "policy_rejected", "provider route is not allowed", 400
            )
        runtime: ProviderRuntime = request.app.state.runtime
        gateway = runtime.gateway
        if not runtime.ready or gateway is None:
            return _error(
                correlation_id,
                "not_ready",
                "provider service is not ready",
                503,
                retryable=True,
            )
        timeout = _deadline_timeout(context, payload.timeout_seconds)
        operation = CompletionRequest(
            messages=payload.messages,
            route=payload.route,
            request_id=payload.request_id,
            operation=payload.operation,
            request_class=payload.request_class,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
            timeout_seconds=timeout,
            idempotency_key=payload.idempotency_key,
            metadata=payload.metadata,
            tools=payload.tools,
            tool_choice=payload.tool_choice,
        )
    except InternalAuthenticationError as exc:
        return _error(correlation_id, exc.code, str(exc), 401)
    except (InternalContextValidationError, ValidationError):
        return _error(
            correlation_id, "invalid_context", "request context is invalid", 400
        )
    except TimeoutError:
        return _error(
            correlation_id,
            "deadline_exceeded",
            "request deadline expired",
            504,
            retryable=True,
        )

    async def events() -> AsyncIterator[str]:
        principal_token = _bind_principal(context)
        emitted = False
        next_sequence = 0
        try:
            async with asyncio.timeout(_deadline_timeout(context, timeout)):
                async for event in gateway.astream(operation):
                    emitted = emitted or event.kind in {"delta", "completed"}
                    next_sequence = max(next_sequence, event.sequence + 1)
                    payload_json = json.dumps(
                        {
                            "correlation_id": context.correlation_id,
                            "contract_version": INTERNAL_CONTRACT_VERSION,
                            "schema_version": LLM_SERVICE_CONTRACT_VERSION,
                            "event": event.model_dump(mode="json"),
                        },
                        separators=(",", ":"),
                    )
                    yield f"data: {payload_json}\n\n"
        except Exception as exc:
            if isinstance(exc, TimeoutError):
                error_code = "deadline_exceeded"
            elif emitted:
                error_code = "stream_interrupted"
            elif isinstance(exc, LLMProviderError):
                error_code = exc.code.value
            else:
                error_code = "unavailable"
            failure = {
                "kind": "error",
                "request_id": operation.request_id,
                "sequence": next_sequence,
                "model": operation.route.alias,
                "error_code": error_code,
                "error_reason": (
                    "request deadline expired"
                    if error_code == "deadline_exceeded"
                    else "provider stream failed"
                ),
            }
            yield (
                "data: "
                + json.dumps(
                    {
                        "correlation_id": context.correlation_id,
                        "contract_version": INTERNAL_CONTRACT_VERSION,
                        "schema_version": LLM_SERVICE_CONTRACT_VERSION,
                        "event": failure,
                    },
                    separators=(",", ":"),
                )
                + "\n\n"
            )
        finally:
            reset_provider_principal(principal_token)

    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/v1/provider-keys/{action}", response_model=None)
async def provider_keys(action: str, request: Request) -> JSONResponse:
    correlation_id = "unknown"
    try:
        context, raw_input = await _authorized_body(request)
        correlation_id = context.correlation_id
        runtime: ProviderRuntime = request.app.state.runtime
        if not runtime.ready or runtime.settings is None:
            return _error(
                correlation_id,
                "not_ready",
                "provider service is not ready",
                503,
                retryable=True,
            )
        timeout = _deadline_timeout(context, 10.0)
        user_id = context.principal.subject_id
        result: KeyListResult | KeyMutationResult | KeyTestResult | KeyDeleteResult
        payload: KeyCreateInput | KeyReplaceInput | KeyIdInput
        async with asyncio.timeout(timeout):
            if action == "list":
                keys = await runtime.settings.list_keys(user_id=user_id)
                result = KeyListResult(keys=tuple(_summary(key) for key in keys))
            elif action == "create":
                payload = KeyCreateInput.model_validate(raw_input)
                key = await runtime.settings.add_key(
                    user_id=user_id,
                    key=payload.api_key.get_secret_value(),
                    label=payload.label,
                )
                result = KeyMutationResult(key=_summary(key))
            elif action == "replace":
                payload = KeyReplaceInput.model_validate(raw_input)
                key = await runtime.settings.replace_key(
                    user_id=user_id,
                    key_id=payload.key_id,
                    key=payload.api_key.get_secret_value(),
                    label=payload.label,
                )
                result = KeyMutationResult(key=_summary(key))
            elif action == "test":
                payload = KeyIdInput.model_validate(raw_input)
                passed = await runtime.settings.test_key(
                    user_id=user_id, key_id=payload.key_id
                )
                result = KeyTestResult(
                    id=payload.key_id,
                    passed=passed,
                    status="healthy" if passed else "unavailable",
                )
            elif action == "delete":
                payload = KeyIdInput.model_validate(raw_input)
                await runtime.settings.delete_key(
                    user_id=user_id, key_id=payload.key_id
                )
                result = KeyDeleteResult()
            else:
                return _error(
                    correlation_id,
                    "invalid_argument",
                    "provider-key operation is not supported",
                    404,
                )
        return JSONResponse(content=_success(context, result.model_dump(mode="json")))
    except InternalAuthenticationError as exc:
        return _error(correlation_id, exc.code, str(exc), 401)
    except (InternalContextValidationError, ValidationError):
        return _error(
            correlation_id, "invalid_context", "request context is invalid", 400
        )
    except ProviderSettingsError as exc:
        status = _PROVIDER_KEY_ERROR_STATUSES.get(exc.code, 502)
        return _error(correlation_id, exc.code, "provider-key operation failed", status)
    except TimeoutError:
        return _error(
            correlation_id,
            "deadline_exceeded",
            "request deadline expired",
            504,
            retryable=True,
        )
    except Exception:
        return _error(
            correlation_id,
            "unavailable",
            "LLM provider is unavailable",
            503,
            retryable=True,
        )


@app.post("/v1/settings/{action}", response_model=None)
async def settings(action: str, request: Request) -> JSONResponse:
    correlation_id = "unknown"
    try:
        context, raw_input = await _authorized_body(request)
        correlation_id = context.correlation_id
        runtime: ProviderRuntime = request.app.state.runtime
        if not runtime.ready or runtime.settings is None:
            return _error(
                correlation_id,
                "not_ready",
                "provider service is not ready",
                503,
                retryable=True,
            )
        timeout = _deadline_timeout(context, 10.0)
        async with asyncio.timeout(timeout):
            if action == "read":
                selected, models = await runtime.settings.selected_model_settings()
            elif action == "update":
                payload = SettingsUpdateInput.model_validate(raw_input)
                await runtime.settings.update_selected_model(
                    model_id=payload.selected_model,
                    user_id=context.principal.subject_id,
                )
                selected, models = await runtime.settings.selected_model_settings()
            else:
                return _error(
                    correlation_id,
                    "invalid_argument",
                    "settings operation is not supported",
                    404,
                )
        result = SettingsResult(
            selected_model=selected,
            models=tuple(
                ModelSummary(
                    id=model.id,
                    name=model.name,
                    description=model.description,
                    context_length=model.context_length,
                )
                for model in models
            ),
        )
        return JSONResponse(content=_success(context, result.model_dump(mode="json")))
    except InternalAuthenticationError as exc:
        return _error(correlation_id, exc.code, str(exc), 401)
    except (InternalContextValidationError, ValidationError):
        return _error(
            correlation_id, "invalid_context", "request context is invalid", 400
        )
    except ProviderSettingsError as exc:
        status = 400 if exc.code in {"model_not_free", "invalid_key"} else 502
        return _error(
            correlation_id, exc.code, "provider settings operation failed", status
        )
    except TimeoutError:
        return _error(
            correlation_id,
            "deadline_exceeded",
            "request deadline expired",
            504,
            retryable=True,
        )
    except Exception:
        return _error(
            correlation_id,
            "unavailable",
            "LLM provider is unavailable",
            503,
            retryable=True,
        )
