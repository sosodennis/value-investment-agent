from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator, Collection, Iterator, Mapping
from datetime import UTC, datetime
from threading import Thread
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError

from src.llm_provider_service.application.context import get_provider_principal
from src.llm_provider_service.domain.contracts import (
    ChatMessage,
    ChatRole,
    CompletionRequest,
    CompletionResult,
    LLMAttempt,
    LLMAttribution,
    LLMErrorCode,
    LLMProviderError,
    LLMRequestClass,
    LLMRouteResolver,
    ResolvedModelRoute,
    StreamEvent,
    StructuredRequest,
    Usage,
)
from src.llm_provider_service.domain.key_metadata import key_fingerprint, key_suffix
from src.llm_provider_service.domain.provider_models import ManagedProviderKey
from src.llm_provider_service.domain.routes import UserScopedRouteResolver
from src.llm_provider_service.infrastructure.state import (
    ProviderDeployment,
    ProviderState,
)

from .telemetry import LLMProviderTelemetry

_T = TypeVar("_T", bound=BaseModel)
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_REVISION_KEY = "via:llm-provider:deployments:revision"
_STRUCTURED_SCHEMA_RETRY_LIMIT = 1
_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
_MAX_RETRY_ATTEMPTS = 3
_logger = logging.getLogger(__name__)


def _value(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _message(response: object) -> object:
    choices = _value(response, "choices", ())
    if not choices:
        raise ValueError("provider response has no choices")
    return _value(choices[0], "message", {})


def _text(response: object) -> str:
    content = _value(_message(response), "content", "")
    return content if isinstance(content, str) else ""


def _usage(response: object) -> Usage | None:
    raw = _value(response, "usage")
    if raw is None:
        return None
    return Usage(
        prompt_tokens=_as_int(_value(raw, "prompt_tokens")),
        completion_tokens=_as_int(_value(raw, "completion_tokens")),
        total_tokens=_as_int(_value(raw, "total_tokens")),
        cost_usd=_as_float(_value(raw, "cost")),
    )


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


def _as_float(value: object) -> float | None:
    return value if isinstance(value, (int | float)) and value >= 0 else None


def _retry_after(response: object) -> float | None:
    headers = _value(response, "headers", {})
    raw = _value(headers, "retry-after")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None


def _tool_calls(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list | tuple):
        return ()
    result: list[dict[str, object]] = []
    for item in value:
        if isinstance(item, Mapping):
            result.append({str(key): val for key, val in item.items()})
        elif hasattr(item, "model_dump"):
            dumped = item.model_dump(mode="json")
            if isinstance(dumped, dict):
                result.append(dumped)
    return tuple(result)


def _validation_issues(exc: Exception) -> list[dict[str, str]]:
    if isinstance(exc, ValidationError):
        return [
            {
                "path": ".".join(str(part)[:80] for part in issue["loc"]),
                "type": str(issue["type"]),
            }
            for issue in exc.errors(include_input=False, include_url=False)[:20]
        ]
    return [{"path": "$", "type": "invalid_json"}]


def _model_list(
    deployments: list[ProviderDeployment], keys: Mapping[str, str]
) -> list[dict[str, object]]:
    return [
        {
            "model_name": f"openrouter-user-{_user_hash(deployment.user_id)}",
            "litellm_params": {
                "model": (
                    deployment.model
                    if deployment.model.startswith("openrouter/")
                    else f"openrouter/{deployment.model}"
                ),
                "api_base": _OPENROUTER_BASE_URL,
                "api_key": keys[deployment.id],
                "headers": {
                    "HTTP-Referer": os.getenv("OPENROUTER_HTTP_REFERER", ""),
                    "X-Title": os.getenv(
                        "OPENROUTER_X_TITLE", "Value Investment Agent"
                    ),
                },
            },
            "model_info": {
                "id": deployment.id,
                "managed_key_id": deployment.id,
                "fingerprint": deployment.fingerprint,
            },
        }
        for deployment in deployments
        if deployment.status not in {"invalid_key", "disabled"}
    ]


def _user_hash(user_id: str) -> str:
    from hashlib import sha256

    return sha256(user_id.encode("utf-8")).hexdigest()[:20]


def _run_sync(factory: Any) -> Any:
    """Run an async provider call from sync code, including inside an event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    result: list[Any] = []
    failure: list[BaseException] = []

    def runner() -> None:
        try:
            result.append(asyncio.run(factory()))
        except BaseException as exc:  # propagate the original provider error
            failure.append(exc)

    thread = Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if failure:
        raise failure[0]
    return result[0]


class EmbeddedLiteLLMProvider:
    """Provider-owned LiteLLM Router and deployment control plane.

    The Router is deliberately long-lived per process. Database-backed
    deployment snapshots are rebuilt only after a mutation or replica revision
    change, so request handling never creates process-local routing state.
    """

    provider_name = "litellm"

    def __init__(
        self,
        state: ProviderState,
        *,
        route_resolver: LLMRouteResolver | None = None,
        telemetry: LLMProviderTelemetry | None = None,
        redis_client: Redis | None = None,
    ) -> None:
        self._state = state
        self._route_resolver = route_resolver or UserScopedRouteResolver()
        self.telemetry = telemetry or LLMProviderTelemetry()
        self._router: Any = None
        self._revision = 0
        self._refresh_lock = asyncio.Lock()
        self._redis = redis_client or Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            password=os.getenv("REDIS_PASSWORD") or None,
            decode_responses=True,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
        )

    async def start(self) -> None:
        await self._redis.ping()
        await self._refresh()

    async def close(self) -> None:
        self._router = None
        await self._redis.aclose()

    async def aclose(self) -> None:
        await self.close()

    async def _refresh(self) -> None:
        async with self._refresh_lock:
            deployments = await self._state.list_deployments()
            keys = {
                deployment.id: await self._state.deployment_key(deployment.id)
                for deployment in deployments
            }
            from litellm import Router

            redis_host = os.getenv("REDIS_HOST", "localhost")
            redis_port = int(os.getenv("REDIS_PORT", "6379"))
            self._router = Router(
                model_list=_model_list(deployments, keys),
                redis_host=redis_host,
                redis_port=redis_port,
                redis_password=os.getenv("REDIS_PASSWORD") or None,
                num_retries=1,
                retry_after=1,
                max_fallbacks=0,
                default_fallbacks=[],
                fallbacks=[],
                context_window_fallbacks=[],
                content_policy_fallbacks=[],
                allowed_fails=0,
                cooldown_time=float(
                    os.getenv("LLM_PROVIDER_KEY_COOLDOWN_SECONDS", "30")
                ),
                routing_strategy="simple-shuffle",
            )
            self._revision = await self._read_revision()

    async def _read_revision(self) -> int:
        value = await self._redis.get(_REVISION_KEY)
        if value is None:
            return 0
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("LLM provider deployment revision is invalid") from exc

    async def _revision_changed(self) -> bool:
        return await self._read_revision() != self._revision

    async def _publish_revision(self) -> None:
        self._revision = int(await self._redis.incr(_REVISION_KEY))

    async def _ensure_router(self) -> Any:
        if self._router is None or await self._revision_changed():
            await self._refresh()
        return self._router

    def _resolve(self, request: CompletionRequest) -> ResolvedModelRoute:
        principal = get_provider_principal()
        if principal is None:
            raise LLMProviderError(
                code=LLMErrorCode.PROVIDER_CONTEXT_MISSING,
                provider=self.provider_name,
                model=request.route.alias,
                request_id=request.request_id,
                reason="authenticated provider principal is required",
                retryable=False,
            )
        try:
            return self._route_resolver.resolve(
                route=request.route, principal=principal
            )
        except ValueError as exc:
            raise LLMProviderError(
                code=LLMErrorCode.POLICY_REJECTED,
                provider=self.provider_name,
                model=request.route.alias,
                request_id=request.request_id,
                reason="provider route is not allowed",
                retryable=False,
            ) from exc

    @staticmethod
    def _messages(messages: Collection[ChatMessage]) -> list[dict[str, object]]:
        return [
            {
                "role": message.role.value,
                "content": message.content,
                **({"name": message.name} if message.name else {}),
                **(
                    {"tool_call_id": message.tool_call_id}
                    if message.tool_call_id
                    else {}
                ),
                **(
                    {"tool_calls": list(message.tool_calls)}
                    if message.tool_calls
                    else {}
                ),
            }
            for message in messages
        ]

    def _kwargs(
        self,
        request: CompletionRequest,
        *,
        response_schema: type[BaseModel] | None = None,
    ) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "messages": self._messages(request.messages),
            "temperature": request.temperature,
            "timeout": request.timeout_seconds,
            "stream": False,
            "metadata": {
                **request.metadata,
                "request_id": request.request_id,
                "operation": request.operation,
            },
            "user": get_provider_principal().user_id,
            "extra_headers": {
                "X-Request-ID": request.request_id,
                **(
                    {"Idempotency-Key": request.idempotency_key}
                    if request.idempotency_key
                    else {}
                ),
            },
        }
        if request.max_tokens is not None:
            kwargs["max_tokens"] = request.max_tokens
        if request.tools:
            kwargs["tools"] = list(request.tools)
        if request.tool_choice is not None:
            kwargs["tool_choice"] = request.tool_choice
        if response_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": response_schema.__name__,
                    "schema": response_schema.model_json_schema(),
                    "strict": True,
                },
            }
        return kwargs

    @staticmethod
    def _response_attribution(
        response: object, resolved: ResolvedModelRoute
    ) -> LLMAttribution | None:
        hidden = _value(response, "_hidden_params", {})
        if not isinstance(hidden, Mapping):
            return resolved.attribution
        deployment_id = hidden.get("model_id") or hidden.get("deployment_id")
        if not isinstance(deployment_id, str) or not deployment_id:
            return resolved.attribution
        return LLMAttribution(
            deployment_id=deployment_id[:255],
            key_fingerprint=(
                resolved.attribution.key_fingerprint
                if resolved.attribution is not None
                else None
            ),
        )

    @staticmethod
    def _retry_delay(attempt: int, error: LLMProviderError | None = None) -> float:
        if error is not None and error.retry_after_seconds is not None:
            return min(8.0, max(0.0, error.retry_after_seconds))
        return min(8.0, 1.0 * (2 ** max(0, attempt - 1)))

    @staticmethod
    def _terminal(
        error: LLMProviderError, attempts: list[LLMAttempt]
    ) -> LLMProviderError:
        return LLMProviderError(
            code=error.code,
            provider=error.provider,
            model=error.model,
            request_id=error.request_id,
            reason=error.reason,
            retryable=False,
            http_status=error.http_status,
            retry_after_seconds=error.retry_after_seconds,
            attempt=error.attempt,
            partial_output=error.partial_output,
            partial_tool_calls=error.partial_tool_calls,
            attribution=error.attribution,
            attempts=tuple(attempts),
        )

    def _malformed(
        self,
        request: CompletionRequest,
        resolved: ResolvedModelRoute,
        *,
        attempt: int,
        reason: str,
    ) -> LLMProviderError:
        return LLMProviderError(
            code=LLMErrorCode.MALFORMED_RESPONSE,
            provider=self.provider_name,
            model=resolved.gateway_alias,
            request_id=request.request_id,
            reason=reason[:500],
            retryable=False,
            attempt=attempt,
            attribution=resolved.attribution,
        )

    def _error(
        self,
        request: CompletionRequest,
        exc: Exception,
        *,
        attempt: int = 1,
        resolved: ResolvedModelRoute | None = None,
    ) -> LLMProviderError:
        status = getattr(exc, "status_code", None)
        response = getattr(exc, "response", None)
        if status is None and response is not None:
            status = getattr(response, "status_code", None)
        if status == 429:
            code = LLMErrorCode.RATE_LIMITED
        elif status in {408, 504} or isinstance(exc, TimeoutError):
            code = LLMErrorCode.UPSTREAM_TIMEOUT
        elif status in {400, 401, 403, 404}:
            code = (
                LLMErrorCode.BAD_REQUEST
                if status == 400
                else LLMErrorCode.AUTHENTICATION_FAILED
            )
        else:
            code = LLMErrorCode.UPSTREAM_UNAVAILABLE
        return LLMProviderError(
            code=code,
            provider=self.provider_name,
            model=request.route.alias,
            request_id=request.request_id,
            reason="LLM provider request failed",
            retryable=code
            in {
                LLMErrorCode.RATE_LIMITED,
                LLMErrorCode.UPSTREAM_TIMEOUT,
                LLMErrorCode.UPSTREAM_UNAVAILABLE,
            },
            http_status=status if isinstance(status, int) else None,
            retry_after_seconds=_retry_after(response),
            attempt=attempt,
            attribution=(resolved.attribution if resolved is not None else None),
        )

    async def acomplete(
        self,
        request: CompletionRequest,
        *,
        response_schema: type[BaseModel] | None = None,
        _record_telemetry: bool = True,
    ) -> CompletionResult:
        started_at = (
            self.telemetry.started(request, stream=False) if _record_telemetry else None
        )
        resolved = self._resolve(request)
        attempts: list[LLMAttempt] = []
        limit = min(
            _MAX_RETRY_ATTEMPTS,
            2 if request.request_class is LLMRequestClass.INTERACTIVE else 3,
        )
        for attempt in range(1, limit + 1):
            retry_error: LLMProviderError | None = None
            try:
                router = await self._ensure_router()
                response = await router.acompletion(
                    model=resolved.gateway_alias,
                    **self._kwargs(request, response_schema=response_schema),
                )
                attribution = self._response_attribution(response, resolved)
                attempt_record = LLMAttempt(
                    attempt=attempt,
                    deployment_id=(attribution.deployment_id if attribution else None),
                    key_fingerprint=(
                        attribution.key_fingerprint if attribution else None
                    ),
                )
                result = CompletionResult(
                    request_id=request.request_id,
                    text=_text(response),
                    model=str(_value(response, "model", request.route.alias)),
                    finish_reason=_value(
                        _value(response, "choices", [{}])[0], "finish_reason"
                    ),
                    usage=_usage(response),
                    attempt=attempt,
                    tool_calls=_tool_calls(
                        _value(_message(response), "tool_calls", ())
                    ),
                    attribution=attribution,
                    attempts=(*attempts, attempt_record),
                )
                if started_at is not None:
                    self.telemetry.succeeded(request, result, started_at=started_at)
                return result
            except LLMProviderError as exc:
                retry_error = exc
                attempts.append(
                    LLMAttempt(
                        attempt=attempt,
                        deployment_id=(
                            exc.attribution.deployment_id if exc.attribution else None
                        ),
                        key_fingerprint=(
                            exc.attribution.key_fingerprint if exc.attribution else None
                        ),
                        error_code=exc.code.value,
                    )
                )
                if not exc.retryable or attempt >= limit:
                    terminal = self._terminal(exc, attempts)
                    if started_at is not None:
                        self.telemetry.failed(request, terminal, started_at=started_at)
                    raise terminal from exc
            except ValueError as exc:
                error = self._malformed(
                    request,
                    resolved,
                    attempt=attempt,
                    reason="provider response was malformed",
                )
                attempts.append(
                    LLMAttempt(attempt=attempt, error_code=error.code.value)
                )
                terminal = self._terminal(error, attempts)
                if started_at is not None:
                    self.telemetry.failed(request, terminal, started_at=started_at)
                raise terminal from exc
            except Exception as exc:
                error = self._error(request, exc, attempt=attempt, resolved=resolved)
                retry_error = error
                attempts.append(
                    LLMAttempt(
                        attempt=attempt,
                        deployment_id=(
                            error.attribution.deployment_id
                            if error.attribution
                            else None
                        ),
                        key_fingerprint=(
                            error.attribution.key_fingerprint
                            if error.attribution
                            else None
                        ),
                        error_code=error.code.value,
                    )
                )
                if not error.retryable or attempt >= limit:
                    terminal = self._terminal(error, attempts)
                    if started_at is not None:
                        self.telemetry.failed(request, terminal, started_at=started_at)
                    raise terminal from exc
            await asyncio.sleep(self._retry_delay(attempt, retry_error))
        raise RuntimeError("unreachable provider retry loop")

    async def acomplete_structured(self, request: StructuredRequest[_T]) -> _T:
        started_at = self.telemetry.started(request.completion, stream=False)
        completion = request.completion.model_copy(
            update={"metadata": {**request.completion.metadata, "structured": "true"}}
        )
        attempt_completion = completion
        all_attempts: list[LLMAttempt] = []
        for structured_attempt in range(1, _STRUCTURED_SCHEMA_RETRY_LIMIT + 2):
            try:
                result = await self.acomplete(
                    attempt_completion.model_copy(
                        update={
                            "idempotency_key": self._structured_idempotency_key(
                                completion, structured_attempt
                            )
                        }
                    ),
                    response_schema=request.response_schema,
                    _record_telemetry=False,
                )
            except LLMProviderError as exc:
                self.telemetry.failed(request.completion, exc, started_at=started_at)
                raise
            all_attempts.extend(result.attempts)
            try:
                decoded = request.response_schema.model_validate_json(result.text)
            except (ValueError, ValidationError) as exc:
                issues = _validation_issues(exc)
                will_retry = structured_attempt <= _STRUCTURED_SCHEMA_RETRY_LIMIT
                _logger.warning(
                    "structured LLM response failed contract validation",
                    extra={
                        "request_id": request.completion.request_id,
                        "operation": request.completion.operation,
                        "structured_attempt": structured_attempt,
                        "will_retry": will_retry,
                        "validation_issues": issues,
                    },
                )
                if will_retry:
                    issue_summary = "\n".join(
                        f"- {item['path']}: {item['type']}" for item in issues
                    )
                    attempt_completion = completion.model_copy(
                        update={
                            "messages": (
                                *completion.messages,
                                ChatMessage(
                                    role=ChatRole.USER,
                                    content=(
                                        "Regenerate the response from the original "
                                        "conversation and satisfy the requested JSON "
                                        "schema. The previous response failed at:\n"
                                        f"{issue_summary}\n"
                                        "Return exactly one JSON object with no "
                                        "markdown or commentary."
                                    ),
                                ),
                            )
                        }
                    )
                    continue
                error = LLMProviderError(
                    code=LLMErrorCode.SCHEMA_VALIDATION_FAILED,
                    provider=self.provider_name,
                    model=result.model,
                    request_id=request.completion.request_id,
                    reason="structured response failed contract validation",
                    retryable=False,
                    attempt=result.attempt,
                    attribution=result.attribution,
                    attempts=tuple(all_attempts),
                )
                self.telemetry.failed(request.completion, error, started_at=started_at)
                raise error from exc
            self.telemetry.succeeded(
                request.completion,
                result.model_copy(update={"attempts": tuple(all_attempts)}),
                started_at=started_at,
            )
            return decoded
        raise RuntimeError("structured response retry loop reached unreachable state")

    @staticmethod
    def _structured_idempotency_key(
        request: CompletionRequest, structured_attempt: int
    ) -> str | None:
        if request.idempotency_key is None:
            return None
        return (
            request.idempotency_key
            if structured_attempt == 1
            else f"{request.idempotency_key}:schema-correction:{structured_attempt - 1}"
        )

    async def astream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        started_at = self.telemetry.started(request, stream=True)
        resolved = self._resolve(request)
        attempts: list[LLMAttempt] = []
        limit = min(
            _MAX_RETRY_ATTEMPTS,
            2 if request.request_class is LLMRequestClass.INTERACTIVE else 3,
        )
        sequence = 0
        first_token_at: float | None = None
        for attempt in range(1, limit + 1):
            emitted = False
            partial_output = ""
            partial_tool_calls: tuple[dict[str, object], ...] = ()
            try:
                router = await self._ensure_router()
                stream = await router.acompletion(
                    model=resolved.gateway_alias,
                    messages=self._messages(request.messages),
                    temperature=request.temperature,
                    timeout=request.timeout_seconds,
                    max_tokens=request.max_tokens,
                    stream=True,
                    stream_options={"include_usage": True},
                    metadata={
                        **request.metadata,
                        "request_id": request.request_id,
                        "operation": request.operation,
                    },
                    user=get_provider_principal().user_id,
                    tools=(list(request.tools) if request.tools else None),
                    tool_choice=request.tool_choice,
                    extra_headers={
                        "X-Request-ID": request.request_id,
                        **(
                            {"Idempotency-Key": request.idempotency_key}
                            if request.idempotency_key
                            else {}
                        ),
                    },
                )
                attribution = self._response_attribution(stream, resolved)
                async for chunk in stream:
                    choices = _value(chunk, "choices", ())
                    usage = _usage(chunk)
                    if not choices:
                        continue
                    delta = _value(choices[0], "delta", {})
                    text = _value(delta, "content", "")
                    tool_calls = _tool_calls(_value(delta, "tool_calls", ()))
                    if not text and not tool_calls:
                        continue
                    if not emitted:
                        emitted = True
                        first_token_at = first_token_at or time.perf_counter()
                        yield StreamEvent(
                            kind="started",
                            request_id=request.request_id,
                            sequence=sequence,
                            model=request.route.alias,
                            attempt=attempt,
                            attribution=attribution,
                        )
                        sequence += 1
                    partial_output += text if isinstance(text, str) else ""
                    partial_tool_calls += tool_calls
                    yield StreamEvent(
                        kind="delta",
                        request_id=request.request_id,
                        sequence=sequence,
                        model=request.route.alias,
                        text=text if isinstance(text, str) else "",
                        tool_calls=tool_calls,
                        usage=usage,
                        attempt=attempt,
                        attribution=attribution,
                    )
                    sequence += 1
                if not emitted:
                    yield StreamEvent(
                        kind="started",
                        request_id=request.request_id,
                        sequence=sequence,
                        model=request.route.alias,
                        attempt=attempt,
                        attribution=resolved.attribution,
                    )
                    sequence += 1
                yield StreamEvent(
                    kind="completed",
                    request_id=request.request_id,
                    sequence=sequence,
                    model=request.route.alias,
                    attempt=attempt,
                    attribution=resolved.attribution,
                )
                result = CompletionResult(
                    request_id=request.request_id,
                    text=partial_output,
                    model=request.route.alias,
                    attempt=attempt,
                    attribution=resolved.attribution,
                    attempts=tuple((*attempts, LLMAttempt(attempt=attempt))),
                )
                self.telemetry.succeeded(
                    request,
                    result,
                    started_at=started_at,
                    first_token_ms=(
                        (first_token_at - started_at) * 1000
                        if first_token_at is not None
                        else None
                    ),
                    stream=True,
                )
                return
            except asyncio.CancelledError:
                self.telemetry.cancelled(request, started_at=started_at, stream=True)
                raise
            except LLMProviderError as exc:
                error = exc
            except Exception as exc:
                error = self._error(request, exc, attempt=attempt, resolved=resolved)
            attempt_record = LLMAttempt(
                attempt=attempt,
                deployment_id=(
                    error.attribution.deployment_id if error.attribution else None
                ),
                key_fingerprint=(
                    error.attribution.key_fingerprint if error.attribution else None
                ),
                error_code=error.code.value,
            )
            attempts.append(attempt_record)
            if emitted:
                interrupted = LLMProviderError(
                    code=LLMErrorCode.STREAM_INTERRUPTED,
                    provider=self.provider_name,
                    model=request.route.alias,
                    request_id=request.request_id,
                    reason="provider stream interrupted after output",
                    retryable=False,
                    attempt=attempt,
                    partial_output=partial_output,
                    partial_tool_calls=partial_tool_calls,
                    attribution=error.attribution,
                    attempts=tuple(attempts),
                )
                self.telemetry.failed(
                    request,
                    interrupted,
                    started_at=started_at,
                    first_token_ms=(
                        (first_token_at - started_at) * 1000
                        if first_token_at is not None
                        else None
                    ),
                    stream=True,
                )
                raise interrupted from error
            if not error.retryable or attempt >= limit:
                terminal = self._terminal(error, attempts)
                self.telemetry.failed(
                    request, terminal, started_at=started_at, stream=True
                )
                raise terminal from error
            await asyncio.sleep(self._retry_delay(attempt, error))
        raise RuntimeError("stream retry loop reached unreachable state")

    def complete(self, request: CompletionRequest) -> CompletionResult:
        return _run_sync(lambda: self.acomplete(request))

    def complete_structured(self, request: StructuredRequest[_T]) -> _T:
        return _run_sync(lambda: self.acomplete_structured(request))

    def stream(self, request: CompletionRequest) -> Iterator[StreamEvent]:
        async def collect() -> list[StreamEvent]:
            return [event async for event in self.astream(request)]

        yield from _run_sync(collect)

    async def list_managed(self) -> list[ManagedProviderKey]:
        return [_managed(item) for item in await self._state.list_deployments()]

    async def add_key(
        self,
        *,
        key: str,
        label: str,
        model: str,
        model_name: str,
        existing_ids: Collection[str],
    ) -> ManagedProviderKey:
        principal = get_provider_principal()
        if principal is None:
            raise RuntimeError("provider principal is required")
        fingerprint = key_fingerprint(key)
        for item in await self._state.list_deployments():
            if (
                item.id in existing_ids
                and item.user_id == principal.user_id
                and item.fingerprint == fingerprint
            ):
                return _managed(item)
        try:
            item = await self._state.create_deployment(
                user_id=principal.user_id,
                key=key,
                label=label,
                suffix=key_suffix(key),
                fingerprint=fingerprint,
                model=model,
            )
        except IntegrityError:
            existing = await self._state.find_deployment_by_fingerprint(
                user_id=principal.user_id, fingerprint=fingerprint
            )
            if existing is None:
                raise
            return _managed(existing)
        await self._refresh()
        await self._publish_revision()
        return _managed(item)

    async def refresh_after_key_import(self) -> None:
        await self._refresh()
        await self._publish_revision()

    async def update_model(self, model: str) -> None:
        await self._state.update_all_deployment_models(model)
        await self._refresh()
        await self._publish_revision()

    async def test_key(self, model_id: str) -> bool:
        item = await self._state.get_deployment(model_id)
        if item is None:
            raise RuntimeError("managed key was not found")
        from src.llm_provider_service.infrastructure.openrouter_key_test import (
            validate_openrouter_key,
        )

        await validate_openrouter_key(await self._state.deployment_key(model_id))
        await self._state.update_deployment(
            model_id,
            status="healthy",
            failure_count=0,
            last_tested_at=datetime.now(UTC),
        )
        return True

    async def mark_replacement_grace(
        self, model_id: str, *, retire_at: datetime
    ) -> None:
        await self._state.update_deployment(
            model_id, status="replacement_grace", replacement_retire_at=retire_at
        )
        await self._refresh()
        await self._publish_revision()

    async def delete_key(self, model_id: str) -> None:
        if await self._state.get_deployment(model_id) is None:
            raise RuntimeError("managed key was not found")
        await self._state.delete_deployment(model_id)
        await self._refresh()
        await self._publish_revision()


def _managed(item: ProviderDeployment) -> ManagedProviderKey:
    return ManagedProviderKey(
        id=item.id,
        label=item.label,
        suffix=item.suffix,
        fingerprint=item.fingerprint,
        created_at=item.created_at,
        status=item.status,
        last_tested_at=item.last_tested_at,
        failure_count=item.failure_count,
        cooldown_until=item.cooldown_until,
        last_used_at=item.last_used_at,
        replacement_retire_at=item.replacement_retire_at,
    )
