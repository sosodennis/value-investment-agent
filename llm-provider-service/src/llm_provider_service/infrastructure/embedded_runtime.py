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
from src.llm_provider_service.domain.reliability import (
    AttemptBudget,
    FailureCategory,
    RetryBudgetExhausted,
    UpstreamFailure,
)
from src.llm_provider_service.domain.routes import OrganizationScopedRouteResolver
from src.llm_provider_service.infrastructure.state import (
    ProviderDeployment,
    ProviderState,
)

from .key_telemetry import RedisProviderKeyTelemetry, _cooldown_expired
from .telemetry import LLMProviderTelemetry
from .upstream_errors import classify_exception

_T = TypeVar("_T", bound=BaseModel)
_OPENROUTER_BASE_URL = os.getenv(
    "OPENROUTER_API_BASE_URL", "https://openrouter.ai/api/v1"
)
_STRUCTURED_SCHEMA_RETRY_LIMIT = 1
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
            "model_name": f"openrouter-org-{_organization_hash(deployment.organization_id)}",
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


def _organization_hash(organization_id: str) -> str:
    from hashlib import sha256

    return sha256(organization_id.encode("utf-8")).hexdigest()[:20]


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
    """Own organization-scoped OpenRouter deployment selection and reliability policy."""

    provider_name = "litellm"

    def __init__(
        self,
        state: ProviderState,
        *,
        route_resolver: LLMRouteResolver | None = None,
        telemetry: LLMProviderTelemetry | None = None,
        redis_client: Redis | None = None,
        key_health: RedisProviderKeyTelemetry | None = None,
    ) -> None:
        self._state = state
        self._route_resolver = route_resolver or OrganizationScopedRouteResolver()
        self.telemetry = telemetry or LLMProviderTelemetry()
        self._key_health = key_health
        self._redis = redis_client

    async def start(self) -> None:
        if self._key_health is not None:
            await self._key_health.ping()
        elif self._redis is not None:
            await self._redis.ping()

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()

    async def aclose(self) -> None:
        await self.close()

    async def _eligible_deployments(
        self, organization_id: str
    ) -> list[ProviderDeployment]:
        deployments = [
            item
            for item in await self._state.list_deployments(
                organization_id=organization_id
            )
            if item.status not in {"invalid_key", "disabled"}
        ]
        if self._key_health is None or not deployments:
            return deployments
        health = await self._key_health.get_many_strict(
            [item.id for item in deployments], organization_id=organization_id
        )
        result: list[ProviderDeployment] = []
        now = datetime.now(UTC)
        for item in deployments:
            current = health.get(item.id)
            if current is None:
                result.append(item)
                continue
            if current.status == "invalid_key":
                continue
            if current.status == "cooldown":
                if not current.cooldown_until or not _cooldown_expired(
                    current.cooldown_until, now
                ):
                    continue
            result.append(item)
        return result

    async def _router_for(self, deployment: ProviderDeployment) -> Any:
        from litellm import Router

        key = await self._state.deployment_key(
            organization_id=deployment.organization_id, deployment_id=deployment.id
        )
        router = Router(
            model_list=_model_list([deployment], {deployment.id: key}),
            num_retries=0,
            max_fallbacks=0,
            default_fallbacks=[],
            fallbacks=[],
        )
        return router

    async def _record_key_use(
        self, deployment_id: str, *, organization_id: str
    ) -> int | None:
        if self._key_health is None:
            return None
        try:
            return await self._key_health.record_use(
                deployment_id, organization_id=organization_id
            )
        except Exception as exc:
            _logger.warning(
                "LLM key use could not be recorded in Redis (%s)", type(exc).__name__
            )
            return None

    async def _record_key_success(
        self,
        deployment_id: str,
        expected_version: int | None,
        *,
        organization_id: str,
    ) -> None:
        if self._key_health is None:
            return
        try:
            await self._key_health.record_success(
                deployment_id,
                organization_id=organization_id,
                expected_version=expected_version,
            )
        except Exception as exc:
            _logger.warning(
                "LLM key success could not be recorded in Redis (%s)",
                type(exc).__name__,
            )

    async def _record_key_failure(
        self, deployment_id: str, failure: UpstreamFailure, *, organization_id: str
    ) -> None:
        if self._key_health is None:
            return
        try:
            await self._key_health.record_failure(
                deployment_id,
                failure,
                organization_id=organization_id,
                cooldown_seconds=float(
                    os.getenv("LLM_PROVIDER_KEY_COOLDOWN_SECONDS", "30")
                ),
            )
        except Exception as exc:
            _logger.warning(
                "LLM key failure could not be recorded in Redis (%s)",
                type(exc).__name__,
            )

    @staticmethod
    def _retry_delay(failure: UpstreamFailure, attempt: int) -> float:
        if failure.retry_after_seconds is not None:
            return failure.retry_after_seconds
        return min(8.0, float(2 ** max(0, attempt - 1)))

    def _failure_error(
        self,
        request: CompletionRequest,
        failure: UpstreamFailure,
        *,
        attempt: int,
        deployment: ProviderDeployment,
        attempts: list[LLMAttempt],
        partial_output: str = "",
        partial_tool_calls: tuple[dict[str, object], ...] = (),
    ) -> LLMProviderError:
        code = {
            FailureCategory.AUTHENTICATION: LLMErrorCode.AUTHENTICATION_FAILED,
            FailureCategory.CREDIT: LLMErrorCode.RATE_LIMITED,
            FailureCategory.RATE_LIMIT: LLMErrorCode.RATE_LIMITED,
            FailureCategory.TIMEOUT: LLMErrorCode.UPSTREAM_TIMEOUT,
            FailureCategory.BAD_REQUEST: LLMErrorCode.BAD_REQUEST,
            FailureCategory.UNAVAILABLE: LLMErrorCode.UPSTREAM_UNAVAILABLE,
        }[failure.category]
        attribution = LLMAttribution(
            deployment_id=deployment.id,
            key_fingerprint=deployment.fingerprint,
        )
        return LLMProviderError(
            code=code,
            provider=self.provider_name,
            model=request.route.alias,
            request_id=request.request_id,
            reason=failure.reason,
            retryable=failure.retryable,
            http_status=failure.http_status,
            retry_after_seconds=failure.retry_after_seconds,
            attempt=attempt,
            partial_output=partial_output,
            partial_tool_calls=partial_tool_calls,
            attribution=attribution,
            attempts=tuple(attempts),
        )

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

    async def acomplete(
        self,
        request: CompletionRequest,
        *,
        response_schema: type[BaseModel] | None = None,
        _record_telemetry: bool = True,
        _budget: AttemptBudget | None = None,
        _attempts: list[LLMAttempt] | None = None,
    ) -> CompletionResult:
        started_at = (
            self.telemetry.started(request, stream=False) if _record_telemetry else None
        )
        resolved = self._resolve(request)
        principal = get_provider_principal()
        if principal is None:
            raise RuntimeError("provider principal is required")
        deployments = await self._eligible_deployments(principal.organization_id)
        limit = min(
            _MAX_RETRY_ATTEMPTS,
            2 if request.request_class is LLMRequestClass.INTERACTIVE else 3,
        )
        budget = _budget or AttemptBudget.from_timeout(limit, request.timeout_seconds)
        attempts = _attempts if _attempts is not None else []
        candidate_index = 0
        retry_deployment: ProviderDeployment | None = None
        retry_error: LLMProviderError | None = None
        last_error: LLMProviderError | None = None
        while candidate_index < len(deployments) or retry_deployment is not None:
            is_same_deployment_retry = retry_deployment is not None
            if retry_deployment is not None:
                deployment = retry_deployment
                retry_deployment = None
            else:
                deployment = deployments[candidate_index]
                candidate_index += 1
            try:
                reservation = budget.reserve(
                    deployment.id, allow_repeat=is_same_deployment_retry
                )
            except RetryBudgetExhausted:
                if is_same_deployment_retry and retry_error is not None:
                    terminal = self._terminal(retry_error, attempts)
                    if started_at is not None:
                        self.telemetry.failed(request, terminal, started_at=started_at)
                    raise terminal from None
                break
            retry_error = None
            try:
                health_version = await self._record_key_use(
                    deployment.id, organization_id=deployment.organization_id
                )
                router = await self._router_for(deployment)
                call_kwargs = self._kwargs(request, response_schema=response_schema)
                call_kwargs["timeout"] = reservation.timeout_seconds
                response = await router.acompletion(
                    model=resolved.gateway_alias, **call_kwargs
                )
                attribution = LLMAttribution(
                    deployment_id=deployment.id, key_fingerprint=deployment.fingerprint
                )
                attempt_record = LLMAttempt(
                    attempt=reservation.attempt,
                    deployment_id=deployment.id,
                    key_fingerprint=deployment.fingerprint,
                )
                attempts.append(attempt_record)
                result = CompletionResult(
                    request_id=request.request_id,
                    text=_text(response),
                    model=str(_value(response, "model", request.route.alias)),
                    finish_reason=_value(
                        _value(response, "choices", [{}])[0], "finish_reason"
                    ),
                    usage=_usage(response),
                    attempt=reservation.attempt,
                    tool_calls=_tool_calls(
                        _value(_message(response), "tool_calls", ())
                    ),
                    attribution=attribution,
                    attempts=tuple(attempts),
                )
                await self._record_key_success(
                    deployment.id,
                    health_version,
                    organization_id=deployment.organization_id,
                )
                if started_at is not None:
                    self.telemetry.succeeded(request, result, started_at=started_at)
                return result
            except ValueError as exc:
                if (
                    attempts
                    and attempts[-1].attempt == reservation.attempt
                    and attempts[-1].error_code is None
                ):
                    attempts.pop()
                error = self._malformed(
                    request,
                    resolved,
                    attempt=reservation.attempt,
                    reason="provider response was malformed",
                )
                attempts.append(
                    LLMAttempt(
                        attempt=reservation.attempt,
                        deployment_id=deployment.id,
                        key_fingerprint=deployment.fingerprint,
                        error_code=error.code.value,
                    )
                )
                terminal = self._terminal(error, attempts)
                if started_at is not None:
                    self.telemetry.failed(request, terminal, started_at=started_at)
                raise terminal from exc
            except Exception as exc:
                failure = classify_exception(exc, deployment.id)
                error = self._failure_error(
                    request,
                    failure,
                    attempt=reservation.attempt,
                    deployment=deployment,
                    attempts=attempts,
                )
                last_error = error
                attempts.append(
                    LLMAttempt(
                        attempt=reservation.attempt,
                        deployment_id=deployment.id,
                        key_fingerprint=deployment.fingerprint,
                        error_code=error.code.value,
                    )
                )
                await self._record_key_failure(
                    deployment.id, failure, organization_id=deployment.organization_id
                )
                if not failure.retryable and not failure.rotates_key:
                    terminal = self._terminal(error, attempts)
                    if started_at is not None:
                        self.telemetry.failed(request, terminal, started_at=started_at)
                    raise terminal from exc
                if failure.rotates_key:
                    continue
                delay = self._retry_delay(failure, reservation.attempt)
                if (
                    budget.used_attempts >= budget.maximum_attempts
                    or not budget.delay_allowed(delay)
                ):
                    terminal = self._terminal(error, attempts)
                    if started_at is not None:
                        self.telemetry.failed(request, terminal, started_at=started_at)
                    raise terminal from exc
                retry_deployment = deployment
                retry_error = error
                await asyncio.sleep(delay)
        if last_error is not None:
            terminal = self._terminal(last_error, attempts)
            if started_at is not None:
                self.telemetry.failed(request, terminal, started_at=started_at)
            raise terminal
        error = LLMProviderError(
            code=LLMErrorCode.FAILOVER_EXHAUSTED,
            provider=self.provider_name,
            model=request.route.alias,
            request_id=request.request_id,
            reason="no eligible provider deployment remains",
            retryable=False,
            attempts=tuple(attempts),
        )
        if started_at is not None:
            self.telemetry.failed(request, error, started_at=started_at)
        raise error

    async def acomplete_structured(self, request: StructuredRequest[_T]) -> _T:
        started_at = self.telemetry.started(request.completion, stream=False)
        completion = request.completion.model_copy(
            update={"metadata": {**request.completion.metadata, "structured": "true"}}
        )
        attempt_completion = completion
        all_attempts: list[LLMAttempt] = []
        budget = AttemptBudget.from_timeout(
            min(
                _MAX_RETRY_ATTEMPTS,
                2 if completion.request_class is LLMRequestClass.INTERACTIVE else 3,
            ),
            completion.timeout_seconds,
        )
        for structured_attempt in range(1, _STRUCTURED_SCHEMA_RETRY_LIMIT + 2):
            try:
                if structured_attempt > 1:
                    budget.attempted_deployments.clear()
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
                    _budget=budget,
                    _attempts=all_attempts,
                )
            except LLMProviderError as exc:
                self.telemetry.failed(request.completion, exc, started_at=started_at)
                raise
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
        principal = get_provider_principal()
        if principal is None:
            raise RuntimeError("provider principal is required")
        deployments = await self._eligible_deployments(principal.organization_id)
        attempts: list[LLMAttempt] = []
        limit = min(
            _MAX_RETRY_ATTEMPTS,
            2 if request.request_class is LLMRequestClass.INTERACTIVE else 3,
        )
        budget = AttemptBudget.from_timeout(limit, request.timeout_seconds)
        sequence = 0
        first_token_at: float | None = None
        candidate_index = 0
        retry_deployment: ProviderDeployment | None = None
        retry_error: LLMProviderError | None = None
        last_error: LLMProviderError | None = None
        while candidate_index < len(deployments) or retry_deployment is not None:
            is_same_deployment_retry = retry_deployment is not None
            if retry_deployment is not None:
                deployment = retry_deployment
                retry_deployment = None
            else:
                deployment = deployments[candidate_index]
                candidate_index += 1
            try:
                reservation = budget.reserve(
                    deployment.id, allow_repeat=is_same_deployment_retry
                )
            except RetryBudgetExhausted:
                if is_same_deployment_retry and retry_error is not None:
                    terminal = self._terminal(retry_error, attempts)
                    self.telemetry.failed(
                        request, terminal, started_at=started_at, stream=True
                    )
                    raise terminal from None
                break
            retry_error = None
            attempt = reservation.attempt
            emitted = False
            partial_output = ""
            partial_tool_calls: tuple[dict[str, object], ...] = ()
            health_version: int | None = None
            try:
                health_version = await self._record_key_use(
                    deployment.id, organization_id=deployment.organization_id
                )
                router = await self._router_for(deployment)
                call_kwargs = {
                    "messages": self._messages(request.messages),
                    "temperature": request.temperature,
                    "timeout": reservation.timeout_seconds,
                    "stream": True,
                    "stream_options": {"include_usage": True},
                    "metadata": {
                        **request.metadata,
                        "request_id": request.request_id,
                        "operation": request.operation,
                    },
                    "user": principal.user_id,
                    "tools": list(request.tools) if request.tools else None,
                    "tool_choice": request.tool_choice,
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
                    call_kwargs["max_tokens"] = request.max_tokens
                stream = await router.acompletion(
                    model=resolved.gateway_alias,
                    **call_kwargs,
                )
                attribution = LLMAttribution(
                    deployment_id=deployment.id,
                    key_fingerprint=deployment.fingerprint,
                )
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
                        attribution=attribution,
                    )
                    sequence += 1
                yield StreamEvent(
                    kind="completed",
                    request_id=request.request_id,
                    sequence=sequence,
                    model=request.route.alias,
                    attempt=attempt,
                    attribution=attribution,
                )
                result = CompletionResult(
                    request_id=request.request_id,
                    text=partial_output,
                    model=request.route.alias,
                    attempt=attempt,
                    attribution=LLMAttribution(
                        deployment_id=deployment.id,
                        key_fingerprint=deployment.fingerprint,
                    ),
                    attempts=tuple(
                        (
                            *attempts,
                            LLMAttempt(
                                attempt=attempt,
                                deployment_id=deployment.id,
                                key_fingerprint=deployment.fingerprint,
                            ),
                        )
                    ),
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
                await self._record_key_success(
                    deployment.id,
                    health_version,
                    organization_id=deployment.organization_id,
                )
                return
            except asyncio.CancelledError:
                self.telemetry.cancelled(request, started_at=started_at, stream=True)
                raise
            except Exception as exc:
                failure = classify_exception(exc, deployment.id)
                error = self._failure_error(
                    request,
                    failure,
                    attempt=attempt,
                    deployment=deployment,
                    attempts=attempts,
                    partial_output=partial_output,
                    partial_tool_calls=partial_tool_calls,
                )
                last_error = error
            attempt_record = LLMAttempt(
                attempt=attempt,
                deployment_id=deployment.id,
                key_fingerprint=deployment.fingerprint,
                error_code=error.code.value,
            )
            attempts.append(attempt_record)
            await self._record_key_failure(
                deployment.id, failure, organization_id=deployment.organization_id
            )
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
            if not error.retryable and not failure.rotates_key:
                terminal = self._terminal(error, attempts)
                self.telemetry.failed(
                    request, terminal, started_at=started_at, stream=True
                )
                raise terminal from error
            if failure.rotates_key:
                continue
            delay = self._retry_delay(failure, attempt)
            if (
                budget.used_attempts >= budget.maximum_attempts
                or not budget.delay_allowed(delay)
            ):
                terminal = self._terminal(error, attempts)
                self.telemetry.failed(
                    request, terminal, started_at=started_at, stream=True
                )
                raise terminal from error
            retry_deployment = deployment
            retry_error = error
            await asyncio.sleep(delay)
        if last_error is not None:
            terminal = self._terminal(last_error, attempts)
            self.telemetry.failed(request, terminal, started_at=started_at, stream=True)
            raise terminal
        terminal = LLMProviderError(
            code=LLMErrorCode.FAILOVER_EXHAUSTED,
            provider=self.provider_name,
            model=request.route.alias,
            request_id=request.request_id,
            reason="no eligible provider deployment remains",
            retryable=False,
            attempts=tuple(attempts),
        )
        self.telemetry.failed(request, terminal, started_at=started_at, stream=True)
        raise terminal

    def complete(self, request: CompletionRequest) -> CompletionResult:
        return _run_sync(lambda: self.acomplete(request))

    def complete_structured(self, request: StructuredRequest[_T]) -> _T:
        return _run_sync(lambda: self.acomplete_structured(request))

    def stream(self, request: CompletionRequest) -> Iterator[StreamEvent]:
        async def collect() -> list[StreamEvent]:
            return [event async for event in self.astream(request)]

        yield from _run_sync(collect)

    async def list_managed(
        self, *, organization_id: str | None = None
    ) -> list[ManagedProviderKey]:
        deployments = (
            await self._state.list_deployments(organization_id=organization_id)
            if organization_id is not None
            else await self._state.list_all_deployments()
        )
        return [_managed(item) for item in deployments]

    async def add_replacement_key(
        self,
        *,
        key: str,
        label: str,
        model: str,
        model_name: str,
        organization_id: str,
        existing_ids: Collection[str],
    ) -> ManagedProviderKey:
        fingerprint = key_fingerprint(key)
        for item in await self._state.list_deployments(organization_id=organization_id):
            if item.id in existing_ids and item.fingerprint == fingerprint:
                return _managed(item)
        try:
            item = await self._state.create_deployment(
                organization_id=organization_id,
                key=key,
                label=label,
                suffix=key_suffix(key),
                fingerprint=fingerprint,
                model=model,
            )
        except IntegrityError:
            existing = await self._state.find_deployment_by_fingerprint(
                organization_id=organization_id, fingerprint=fingerprint
            )
            if existing is None:
                raise
            return _managed(existing)
        return _managed(item)

    async def update_model(self, model: str, *, organization_id: str) -> None:
        await self._state.update_all_deployment_models(
            organization_id=organization_id, model=model
        )

    async def test_key(self, model_id: str) -> bool:
        principal = get_provider_principal()
        if principal is None:
            raise RuntimeError("provider principal is required")
        item = await self._state.get_deployment(
            organization_id=principal.organization_id, deployment_id=model_id
        )
        if item is None:
            raise RuntimeError("managed key was not found")
        from src.llm_provider_service.infrastructure.openrouter_key_test import (
            validate_openrouter_key,
        )

        health_version = await self._record_key_use(
            model_id, organization_id=principal.organization_id
        )
        await validate_openrouter_key(
            await self._state.deployment_key(
                organization_id=principal.organization_id, deployment_id=model_id
            )
        )
        await self._record_key_success(
            model_id, health_version, organization_id=principal.organization_id
        )
        await self._state.update_deployment(
            organization_id=principal.organization_id,
            deployment_id=model_id,
            status="healthy",
            failure_count=0,
            last_tested_at=datetime.now(UTC),
        )
        return True

    async def mark_replacement_grace(
        self,
        model_id: str,
        *,
        organization_id: str,
        retire_at: datetime,
    ) -> None:
        await self._state.update_deployment(
            organization_id=organization_id,
            deployment_id=model_id,
            status="replacement_grace",
            replacement_retire_at=retire_at,
        )

    async def delete_key(self, model_id: str, *, organization_id: str) -> None:
        if (
            await self._state.get_deployment(
                organization_id=organization_id, deployment_id=model_id
            )
            is None
        ):
            raise RuntimeError("managed key was not found")
        await self._state.delete_deployment(
            organization_id=organization_id, deployment_id=model_id
        )


def _managed(item: ProviderDeployment) -> ManagedProviderKey:
    return ManagedProviderKey(
        id=item.id,
        label=item.label,
        suffix=item.suffix,
        fingerprint=item.fingerprint,
        created_at=item.created_at,
        organization_id=item.organization_id,
        status=item.status,
        last_tested_at=item.last_tested_at,
        failure_count=item.failure_count,
        cooldown_until=item.cooldown_until,
        last_used_at=item.last_used_at,
        replacement_retire_at=item.replacement_retire_at,
    )
