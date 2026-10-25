from __future__ import annotations

import json
import math
import os
import random
import re
import time
from asyncio import CancelledError
from collections.abc import AsyncIterator, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from json import JSONDecodeError
from typing import TypeVar, cast

import httpx
from pydantic import BaseModel, ValidationError

from src.llm_provider_service.application.context import get_provider_principal
from src.llm_provider_service.domain.contracts import (
    ChatMessage,
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
from src.llm_provider_service.domain.routes import UserScopedRouteResolver

from .telemetry import LLMProviderTelemetry

_ResponseModel = TypeVar("_ResponseModel", bound=BaseModel)
_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
_MAX_ERROR_TEXT = 500
_MAX_RETRY_ATTEMPTS = 3
_MAX_METADATA_LENGTH = 128
_SAFE_FINGERPRINT_PATTERN = re.compile(r"(?:sha256:)?[0-9a-fA-F]{12,128}")
_SAFE_DEPLOYMENT_ID_PATTERN = re.compile(
    r"(?:[0-9]{1,20}|deployment-[A-Za-z0-9_-]{1,64}|"
    r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12})"
)


def _env_int(name: str, default: int, *, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def _env_float(name: str, default: float, *, minimum: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(minimum, float(raw))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


@dataclass(frozen=True)
class LiteLLMGatewayConfig:
    base_url: str
    api_key: str
    max_attempts: int = _MAX_RETRY_ATTEMPTS
    attempts_by_request_class: tuple[tuple[LLMRequestClass, int], ...] = (
        (LLMRequestClass.INTERACTIVE, 2),
        (LLMRequestClass.BACKGROUND, 3),
    )
    backoff_seconds: float = 1.0
    max_backoff_seconds: float = 8.0
    jitter_seconds: float = 0.25
    require_principal: bool = False

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= _MAX_RETRY_ATTEMPTS:
            raise ValueError(
                f"max_attempts must be between 1 and {_MAX_RETRY_ATTEMPTS}"
            )
        configured_classes = tuple(
            request_class for request_class, _ in self.attempts_by_request_class
        )
        if set(configured_classes) != set(LLMRequestClass) or len(
            configured_classes
        ) != len(set(configured_classes)):
            raise ValueError(
                "attempts_by_request_class must define every request class once"
            )
        if any(
            not 1 <= attempts <= _MAX_RETRY_ATTEMPTS
            for _, attempts in self.attempts_by_request_class
        ):
            raise ValueError(
                f"request-class attempts must be between 1 and {_MAX_RETRY_ATTEMPTS}"
            )
        for name, value in (
            ("backoff_seconds", self.backoff_seconds),
            ("max_backoff_seconds", self.max_backoff_seconds),
            ("jitter_seconds", self.jitter_seconds),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite non-negative number")

    @classmethod
    def from_env(cls) -> LiteLLMGatewayConfig:
        base_url = os.getenv("LLM_GATEWAY_BASE_URL", "http://localhost:4000")
        api_key = os.getenv("LLM_GATEWAY_API_KEY", "")
        return cls(
            base_url=base_url,
            api_key=api_key,
            max_attempts=min(
                _MAX_RETRY_ATTEMPTS,
                _env_int("LLM_GATEWAY_MAX_ATTEMPTS", _MAX_RETRY_ATTEMPTS, minimum=1),
            ),
            attempts_by_request_class=(
                (
                    LLMRequestClass.INTERACTIVE,
                    min(
                        _MAX_RETRY_ATTEMPTS,
                        _env_int("LLM_GATEWAY_MAX_ATTEMPTS_INTERACTIVE", 2, minimum=1),
                    ),
                ),
                (
                    LLMRequestClass.BACKGROUND,
                    min(
                        _MAX_RETRY_ATTEMPTS,
                        _env_int("LLM_GATEWAY_MAX_ATTEMPTS_BACKGROUND", 3, minimum=1),
                    ),
                ),
            ),
            backoff_seconds=_env_float("LLM_GATEWAY_BACKOFF_SECONDS", 1.0, minimum=0.0),
            max_backoff_seconds=_env_float(
                "LLM_GATEWAY_MAX_BACKOFF_SECONDS", 8.0, minimum=0.0
            ),
            jitter_seconds=_env_float("LLM_GATEWAY_JITTER_SECONDS", 0.25, minimum=0.0),
            require_principal=_env_bool("LLM_GATEWAY_REQUIRE_PRINCIPAL", True),
        )

    def attempts_for(self, request_class: LLMRequestClass) -> int:
        configured = dict(self.attempts_by_request_class)[request_class]
        return min(self.max_attempts, configured)


class LiteLLMGatewayProvider:
    provider_name = "litellm-gateway"

    def __init__(
        self,
        config: LiteLLMGatewayConfig,
        *,
        client: httpx.Client | None = None,
        async_client: httpx.AsyncClient | None = None,
        route_resolver: LLMRouteResolver | None = None,
        telemetry: LLMProviderTelemetry | None = None,
    ) -> None:
        base_url = config.base_url.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"
        headers = {"Authorization": f"Bearer {config.api_key}"}
        self._config = config
        self._client = client or httpx.Client(base_url=base_url, headers=headers)
        self._async_client = async_client or httpx.AsyncClient(
            base_url=base_url, headers=headers
        )
        self._owns_client = client is None
        self._owns_async_client = async_client is None
        self._route_resolver = route_resolver or UserScopedRouteResolver()
        self.telemetry = telemetry or LLMProviderTelemetry()

    def _resolve_route(self, request: CompletionRequest) -> ResolvedModelRoute:
        principal = get_provider_principal()
        if self._config.require_principal and principal is None:
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
                route=request.route,
                principal=principal,
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
    def _response_attribution(
        headers: Mapping[str, str], resolved_route: ResolvedModelRoute
    ) -> LLMAttribution | None:
        deployment_id = _safe_metadata_header(
            headers, "x-litellm-model-id"
        ) or _safe_metadata_header(headers, "x-deployment-id")
        if deployment_id is not None and not _SAFE_DEPLOYMENT_ID_PATTERN.fullmatch(
            deployment_id
        ):
            deployment_id = None
        key_fingerprint = _safe_metadata_header(
            headers, "x-litellm-key-fingerprint"
        ) or _safe_metadata_header(headers, "x-key-fingerprint")
        if key_fingerprint is not None and not _SAFE_FINGERPRINT_PATTERN.fullmatch(
            key_fingerprint
        ):
            key_fingerprint = None
        if deployment_id is None and key_fingerprint is None:
            return resolved_route.attribution
        return LLMAttribution(
            deployment_id=deployment_id,
            key_fingerprint=key_fingerprint,
        )

    @staticmethod
    def _attempt_record(
        *,
        attempt: int,
        attribution: LLMAttribution | None,
        error_code: str | None = None,
    ) -> LLMAttempt:
        return LLMAttempt(
            attempt=attempt,
            deployment_id=attribution.deployment_id if attribution else None,
            key_fingerprint=attribution.key_fingerprint if attribution else None,
            error_code=error_code,
        )

    @classmethod
    def _record_error_attempt(
        cls,
        error: LLMProviderError,
        attempts: list[LLMAttempt],
    ) -> LLMProviderError:
        attempts.append(
            cls._attempt_record(
                attempt=error.attempt,
                attribution=error.attribution,
                error_code=error.code.value,
            )
        )
        error.attempts = tuple(attempts)
        return error

    def complete(self, request: CompletionRequest) -> CompletionResult:
        started_at = self.telemetry.started(request, stream=False)
        try:
            result = self._complete(request)
        except LLMProviderError as exc:
            self.telemetry.failed(request, exc, started_at=started_at)
            raise
        self.telemetry.succeeded(request, result, started_at=started_at)
        return result

    def _complete(
        self,
        request: CompletionRequest,
        *,
        response_schema: type[BaseModel] | None = None,
    ) -> CompletionResult:
        resolved_route = self._resolve_route(request)
        attempts: list[LLMAttempt] = []
        attempt_limit = self._config.attempts_for(request.request_class)
        for attempt in range(1, attempt_limit + 1):
            try:
                response = self._client.post(
                    "/chat/completions",
                    headers=self._request_headers(request),
                    json=self._payload(
                        request,
                        stream=False,
                        response_schema=response_schema,
                        resolved_route=resolved_route,
                    ),
                    timeout=request.timeout_seconds,
                )
                if response.status_code >= 400:
                    self._raise_status(response, request, attempt, resolved_route)
                attribution = self._response_attribution(
                    response.headers, resolved_route
                )
                attempt_record = self._attempt_record(
                    attempt=attempt, attribution=attribution
                )
                result = self._parse_completion(
                    response.json(),
                    request,
                    attempt,
                    resolved_route,
                    attribution,
                    (*attempts, attempt_record),
                )
                attempts.append(attempt_record)
                return result
            except LLMProviderError as exc:
                self._record_error_attempt(exc, attempts)
                if not self._should_retry(exc, attempt, request.request_class):
                    if exc.retryable and attempt >= attempt_limit:
                        raise self._terminal_error(exc) from exc
                    raise
                self._sleep(attempt, exc)
            except httpx.TimeoutException as exc:
                error = self._transport_error(
                    request,
                    attempt,
                    exc,
                    timeout=True,
                    resolved_route=resolved_route,
                )
                self._record_error_attempt(error, attempts)
                if attempt >= attempt_limit:
                    raise self._terminal_error(error) from exc
                self._sleep(attempt, error)
            except httpx.RequestError as exc:
                error = self._transport_error(
                    request,
                    attempt,
                    exc,
                    timeout=False,
                    resolved_route=resolved_route,
                )
                self._record_error_attempt(error, attempts)
                if attempt >= attempt_limit:
                    raise self._terminal_error(error) from exc
                self._sleep(attempt, error)
            except (JSONDecodeError, TypeError, ValueError) as exc:
                error = self._malformed_response(
                    request,
                    attempt,
                    "gateway returned a malformed response",
                    resolved_route,
                )
                self._record_error_attempt(error, attempts)
                raise error from exc
        raise RuntimeError("gateway completion retry loop reached unreachable state")

    def complete_structured(
        self, request: StructuredRequest[_ResponseModel]
    ) -> _ResponseModel:
        started_at = self.telemetry.started(request.completion, stream=False)
        completion = request.completion.model_copy(
            update={"metadata": {**request.completion.metadata, "structured": "true"}}
        )
        try:
            result = self._complete(completion, response_schema=request.response_schema)
            decoded = self._decode_structured_response(result, request)
        except LLMProviderError as exc:
            self.telemetry.failed(request.completion, exc, started_at=started_at)
            raise
        self.telemetry.succeeded(request.completion, result, started_at=started_at)
        return decoded

    async def acomplete(self, request: CompletionRequest) -> CompletionResult:
        started_at = self.telemetry.started(request, stream=False)
        try:
            result = await self._acomplete(request)
        except LLMProviderError as exc:
            self.telemetry.failed(request, exc, started_at=started_at)
            raise
        self.telemetry.succeeded(request, result, started_at=started_at)
        return result

    async def _acomplete(
        self,
        request: CompletionRequest,
        *,
        response_schema: type[BaseModel] | None = None,
    ) -> CompletionResult:
        resolved_route = self._resolve_route(request)
        attempts: list[LLMAttempt] = []
        attempt_limit = self._config.attempts_for(request.request_class)
        for attempt in range(1, attempt_limit + 1):
            try:
                response = await self._async_client.post(
                    "/chat/completions",
                    headers=self._request_headers(request),
                    json=self._payload(
                        request,
                        stream=False,
                        response_schema=response_schema,
                        resolved_route=resolved_route,
                    ),
                    timeout=request.timeout_seconds,
                )
                if response.status_code >= 400:
                    self._raise_status(response, request, attempt, resolved_route)
                attribution = self._response_attribution(
                    response.headers, resolved_route
                )
                attempt_record = self._attempt_record(
                    attempt=attempt, attribution=attribution
                )
                result = self._parse_completion(
                    response.json(),
                    request,
                    attempt,
                    resolved_route,
                    attribution,
                    (*attempts, attempt_record),
                )
                attempts.append(attempt_record)
                return result
            except LLMProviderError as exc:
                self._record_error_attempt(exc, attempts)
                if not self._should_retry(exc, attempt, request.request_class):
                    if exc.retryable and attempt >= attempt_limit:
                        raise self._terminal_error(exc) from exc
                    raise
                await self._async_sleep(attempt, exc)
            except httpx.TimeoutException as exc:
                error = self._transport_error(
                    request,
                    attempt,
                    exc,
                    timeout=True,
                    resolved_route=resolved_route,
                )
                self._record_error_attempt(error, attempts)
                if attempt >= attempt_limit:
                    raise self._terminal_error(error) from exc
                await self._async_sleep(attempt, error)
            except httpx.RequestError as exc:
                error = self._transport_error(
                    request,
                    attempt,
                    exc,
                    timeout=False,
                    resolved_route=resolved_route,
                )
                self._record_error_attempt(error, attempts)
                if attempt >= attempt_limit:
                    raise self._terminal_error(error) from exc
                await self._async_sleep(attempt, error)
            except (JSONDecodeError, TypeError, ValueError) as exc:
                error = self._malformed_response(
                    request,
                    attempt,
                    "gateway returned a malformed response",
                    resolved_route,
                )
                self._record_error_attempt(error, attempts)
                raise error from exc
        raise RuntimeError("gateway completion retry loop reached unreachable state")

    async def acomplete_structured(
        self, request: StructuredRequest[_ResponseModel]
    ) -> _ResponseModel:
        started_at = self.telemetry.started(request.completion, stream=False)
        completion = request.completion.model_copy(
            update={"metadata": {**request.completion.metadata, "structured": "true"}}
        )
        try:
            result = await self._acomplete(
                completion, response_schema=request.response_schema
            )
            decoded = self._decode_structured_response(result, request)
        except LLMProviderError as exc:
            self.telemetry.failed(request.completion, exc, started_at=started_at)
            raise
        self.telemetry.succeeded(request.completion, result, started_at=started_at)
        return decoded

    def _decode_structured_response(
        self,
        result: CompletionResult,
        request: StructuredRequest[_ResponseModel],
    ) -> _ResponseModel:
        try:
            decoded: object = json.loads(result.text)
            return request.response_schema.model_validate(decoded)
        except (JSONDecodeError, TypeError, ValidationError) as exc:
            raise LLMProviderError(
                code=LLMErrorCode.SCHEMA_VALIDATION_FAILED,
                provider=self.provider_name,
                model=result.model,
                request_id=request.completion.request_id,
                reason="gateway response did not match the requested schema",
                retryable=False,
                attempt=result.attempt,
                attribution=result.attribution,
                attempts=result.attempts,
            ) from exc

    def stream(self, request: CompletionRequest) -> Iterator[StreamEvent]:
        started_at = self.telemetry.started(request, stream=True)
        first_token_at: float | None = None
        last_event: StreamEvent | None = None
        try:
            for event in self._stream(request):
                if event.kind == "delta" and first_token_at is None:
                    first_token_at = time.perf_counter()
                last_event = event
                yield event
        except GeneratorExit:
            self.telemetry.cancelled(request, started_at=started_at, stream=True)
            raise
        except LLMProviderError as exc:
            first_token_ms = (
                (first_token_at - started_at) * 1000 if first_token_at else None
            )
            self.telemetry.failed(
                request,
                exc,
                started_at=started_at,
                first_token_ms=first_token_ms,
                stream=True,
            )
            raise
        else:
            result = CompletionResult(
                request_id=request.request_id,
                text="",
                model=last_event.model if last_event else request.route.alias,
                attempt=last_event.attempt if last_event else 1,
                usage=last_event.usage if last_event else None,
                attribution=last_event.attribution if last_event else None,
                attempts=(),
            )
            self.telemetry.succeeded(
                request,
                result,
                started_at=started_at,
                first_token_ms=(
                    (first_token_at - started_at) * 1000 if first_token_at else None
                ),
                stream=True,
            )

    def _stream(self, request: CompletionRequest) -> Iterator[StreamEvent]:
        resolved_route = self._resolve_route(request)
        attempts: list[LLMAttempt] = []
        attempt_limit = self._config.attempts_for(request.request_class)
        for attempt in range(1, attempt_limit + 1):
            emitted = False
            partial_output = ""
            partial_tool_calls: tuple[dict[str, object], ...] = ()
            sequence = 0
            model = resolved_route.gateway_alias
            attempt_route = resolved_route
            try:
                with self._client.stream(
                    "POST",
                    "/chat/completions",
                    headers=self._request_headers(request),
                    json=self._payload(
                        request, stream=True, resolved_route=resolved_route
                    ),
                    timeout=request.timeout_seconds,
                ) as response:
                    if response.status_code >= 400:
                        self._raise_status(response, request, attempt, resolved_route)
                    attempt_route = resolved_route.model_copy(
                        update={
                            "attribution": self._response_attribution(
                                response.headers, resolved_route
                            )
                        }
                    )
                    completed = False
                    for line in response.iter_lines():
                        event = self._stream_event_from_line(
                            line,
                            request,
                            attempt,
                            model,
                            sequence,
                            attempt_route,
                        )
                        if event is None:
                            continue
                        model = event.model
                        if event.kind == "delta":
                            if not emitted:
                                yield StreamEvent(
                                    kind="started",
                                    request_id=request.request_id,
                                    sequence=0,
                                    model=model,
                                    attempt=attempt,
                                    attribution=attempt_route.attribution,
                                )
                            emitted = True
                            sequence = event.sequence
                            partial_output += event.text
                            partial_tool_calls += event.tool_calls
                            yield event
                        elif event.kind == "completed":
                            if not emitted:
                                yield StreamEvent(
                                    kind="started",
                                    request_id=request.request_id,
                                    sequence=0,
                                    model=model,
                                    attempt=attempt,
                                    attribution=attempt_route.attribution,
                                )
                            yield event
                            completed = True
                            break
                    if not completed:
                        raise self._malformed_response(
                            request,
                            attempt,
                            "gateway stream ended without a completion marker",
                            attempt_route,
                        )
                    return
            except LLMProviderError as exc:
                if emitted or not self._should_retry(
                    exc, attempt, request.request_class
                ):
                    if emitted and exc.code != LLMErrorCode.STREAM_INTERRUPTED:
                        error = self._stream_interrupted(
                            request,
                            attempt,
                            partial_output,
                            partial_tool_calls=partial_tool_calls,
                            resolved_route=attempt_route,
                        )
                        self._record_error_attempt(error, attempts)
                        raise error from exc
                    self._record_error_attempt(exc, attempts)
                    if exc.retryable and attempt >= attempt_limit:
                        raise self._terminal_error(exc) from exc
                    raise
                self._record_error_attempt(exc, attempts)
                self._sleep(attempt, exc)
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                if emitted:
                    error = self._stream_interrupted(
                        request,
                        attempt,
                        partial_output,
                        partial_tool_calls=partial_tool_calls,
                        resolved_route=attempt_route,
                    )
                    self._record_error_attempt(error, attempts)
                    raise error from exc
                error = self._transport_error(
                    request,
                    attempt,
                    exc,
                    timeout=isinstance(exc, httpx.TimeoutException),
                    resolved_route=attempt_route,
                )
                self._record_error_attempt(error, attempts)
                if attempt >= attempt_limit:
                    raise self._terminal_error(error) from exc
                self._sleep(attempt, error)
            except (JSONDecodeError, TypeError, ValueError) as exc:
                if emitted:
                    error = self._stream_interrupted(
                        request,
                        attempt,
                        partial_output,
                        partial_tool_calls=partial_tool_calls,
                        resolved_route=attempt_route,
                    )
                    self._record_error_attempt(error, attempts)
                    raise error from exc
                error = self._malformed_response(
                    request,
                    attempt,
                    "gateway returned a malformed response",
                    attempt_route,
                )
                self._record_error_attempt(error, attempts)
                raise error from exc
        raise RuntimeError("gateway stream retry loop reached unreachable state")

    async def astream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        started_at = self.telemetry.started(request, stream=True)
        first_token_at: float | None = None
        last_event: StreamEvent | None = None
        try:
            async for event in self._astream(request):
                if event.kind == "delta" and first_token_at is None:
                    first_token_at = time.perf_counter()
                last_event = event
                yield event
        except CancelledError:
            self.telemetry.cancelled(request, started_at=started_at, stream=True)
            raise
        except GeneratorExit:
            self.telemetry.cancelled(request, started_at=started_at, stream=True)
            raise
        except LLMProviderError as exc:
            first_token_ms = (
                (first_token_at - started_at) * 1000 if first_token_at else None
            )
            self.telemetry.failed(
                request,
                exc,
                started_at=started_at,
                first_token_ms=first_token_ms,
                stream=True,
            )
            raise
        else:
            result = CompletionResult(
                request_id=request.request_id,
                text="",
                model=last_event.model if last_event else request.route.alias,
                attempt=last_event.attempt if last_event else 1,
                usage=last_event.usage if last_event else None,
                attribution=last_event.attribution if last_event else None,
                attempts=(),
            )
            self.telemetry.succeeded(
                request,
                result,
                started_at=started_at,
                first_token_ms=(
                    (first_token_at - started_at) * 1000 if first_token_at else None
                ),
                stream=True,
            )

    async def _astream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        resolved_route = self._resolve_route(request)
        attempts: list[LLMAttempt] = []
        attempt_limit = self._config.attempts_for(request.request_class)
        for attempt in range(1, attempt_limit + 1):
            emitted = False
            partial_output = ""
            partial_tool_calls: tuple[dict[str, object], ...] = ()
            sequence = 0
            model = resolved_route.gateway_alias
            attempt_route = resolved_route
            try:
                async with self._async_client.stream(
                    "POST",
                    "/chat/completions",
                    headers=self._request_headers(request),
                    json=self._payload(
                        request, stream=True, resolved_route=resolved_route
                    ),
                    timeout=request.timeout_seconds,
                ) as response:
                    if response.status_code >= 400:
                        await self._raise_status_async(
                            response, request, attempt, resolved_route
                        )
                    attempt_route = resolved_route.model_copy(
                        update={
                            "attribution": self._response_attribution(
                                response.headers, resolved_route
                            )
                        }
                    )
                    completed = False
                    async for line in response.aiter_lines():
                        event = self._stream_event_from_line(
                            line,
                            request,
                            attempt,
                            model,
                            sequence,
                            attempt_route,
                        )
                        if event is None:
                            continue
                        model = event.model
                        if event.kind == "delta":
                            if not emitted:
                                yield StreamEvent(
                                    kind="started",
                                    request_id=request.request_id,
                                    sequence=0,
                                    model=model,
                                    attempt=attempt,
                                    attribution=attempt_route.attribution,
                                )
                            emitted = True
                            sequence = event.sequence
                            partial_output += event.text
                            partial_tool_calls += event.tool_calls
                            yield event
                        elif event.kind == "completed":
                            if not emitted:
                                yield StreamEvent(
                                    kind="started",
                                    request_id=request.request_id,
                                    sequence=0,
                                    model=model,
                                    attempt=attempt,
                                    attribution=attempt_route.attribution,
                                )
                            yield event
                            completed = True
                            break
                    if not completed:
                        raise self._malformed_response(
                            request,
                            attempt,
                            "gateway stream ended without a completion marker",
                            attempt_route,
                        )
                    return
            except LLMProviderError as exc:
                if emitted or not self._should_retry(
                    exc, attempt, request.request_class
                ):
                    if emitted and exc.code != LLMErrorCode.STREAM_INTERRUPTED:
                        error = self._stream_interrupted(
                            request,
                            attempt,
                            partial_output,
                            partial_tool_calls=partial_tool_calls,
                            resolved_route=attempt_route,
                        )
                        self._record_error_attempt(error, attempts)
                        raise error from exc
                    self._record_error_attempt(exc, attempts)
                    if exc.retryable and attempt >= attempt_limit:
                        raise self._terminal_error(exc) from exc
                    raise
                self._record_error_attempt(exc, attempts)
                await self._async_sleep(attempt, exc)
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                if emitted:
                    error = self._stream_interrupted(
                        request,
                        attempt,
                        partial_output,
                        partial_tool_calls=partial_tool_calls,
                        resolved_route=attempt_route,
                    )
                    self._record_error_attempt(error, attempts)
                    raise error from exc
                error = self._transport_error(
                    request,
                    attempt,
                    exc,
                    timeout=isinstance(exc, httpx.TimeoutException),
                    resolved_route=attempt_route,
                )
                self._record_error_attempt(error, attempts)
                if attempt >= attempt_limit:
                    raise self._terminal_error(error) from exc
                await self._async_sleep(attempt, error)
            except (JSONDecodeError, TypeError, ValueError) as exc:
                if emitted:
                    error = self._stream_interrupted(
                        request,
                        attempt,
                        partial_output,
                        partial_tool_calls=partial_tool_calls,
                        resolved_route=attempt_route,
                    )
                    self._record_error_attempt(error, attempts)
                    raise error from exc
                error = self._malformed_response(
                    request,
                    attempt,
                    "gateway returned a malformed response",
                    attempt_route,
                )
                self._record_error_attempt(error, attempts)
                raise error from exc
        raise RuntimeError("gateway stream retry loop reached unreachable state")

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    async def aclose(self) -> None:
        if self._owns_async_client:
            await self._async_client.aclose()
        self.close()

    def _payload(
        self,
        request: CompletionRequest,
        *,
        stream: bool,
        response_schema: type[BaseModel] | None = None,
        resolved_route: ResolvedModelRoute,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": resolved_route.gateway_alias,
            "messages": [
                self._message_payload(message) for message in request.messages
            ],
            "temperature": request.temperature,
            "stream": stream,
        }
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if stream:
            payload["stream_options"] = {"include_usage": True}
        if response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": response_schema.__name__,
                    "schema": response_schema.model_json_schema(),
                    "strict": True,
                },
            }
        if request.tools:
            payload["tools"] = list(request.tools)
        if request.tool_choice is not None:
            payload["tool_choice"] = request.tool_choice
        return payload

    @staticmethod
    def _message_payload(message: ChatMessage) -> dict[str, object]:
        payload: dict[str, object] = {
            "role": message.role.value,
            "content": message.content,
        }
        if message.name is not None:
            payload["name"] = message.name
        if message.tool_call_id is not None:
            payload["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            payload["tool_calls"] = list(message.tool_calls)
        return payload

    def _request_headers(self, request: CompletionRequest) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "X-Request-ID": request.request_id,
        }
        if request.idempotency_key:
            headers["Idempotency-Key"] = request.idempotency_key
        return headers

    def _raise_status(
        self,
        response: httpx.Response,
        request: CompletionRequest,
        attempt: int,
        resolved_route: ResolvedModelRoute,
    ) -> None:
        raise self._status_error(response, request, attempt, resolved_route)

    async def _raise_status_async(
        self,
        response: httpx.Response,
        request: CompletionRequest,
        attempt: int,
        resolved_route: ResolvedModelRoute,
    ) -> None:
        raise self._status_error(response, request, attempt, resolved_route)

    def _status_error(
        self,
        response: httpx.Response,
        request: CompletionRequest,
        attempt: int,
        resolved_route: ResolvedModelRoute,
    ) -> LLMProviderError:
        status = response.status_code
        if status in {401, 403}:
            code = LLMErrorCode.AUTHENTICATION_FAILED
            reason = "gateway authentication failed"
        elif status == 429:
            code = LLMErrorCode.RATE_LIMITED
            reason = "gateway rate limited the request"
        elif status == 408:
            code = LLMErrorCode.UPSTREAM_TIMEOUT
            reason = "gateway request timed out"
        elif status in {400, 422}:
            code = LLMErrorCode.BAD_REQUEST
            reason = "gateway rejected the request"
        elif status >= 500:
            code = LLMErrorCode.UPSTREAM_UNAVAILABLE
            reason = "gateway upstream is unavailable"
        else:
            code = LLMErrorCode.UPSTREAM_UNAVAILABLE
            reason = "gateway request failed"
        return LLMProviderError(
            code=code,
            provider=self.provider_name,
            model=resolved_route.gateway_alias,
            request_id=request.request_id,
            reason=reason,
            retryable=status in _RETRYABLE_STATUS_CODES,
            http_status=status,
            retry_after_seconds=_retry_after_seconds(response.headers),
            attempt=attempt,
            attribution=self._response_attribution(response.headers, resolved_route),
        )

    def _transport_error(
        self,
        request: CompletionRequest,
        attempt: int,
        exc: Exception,
        *,
        timeout: bool,
        resolved_route: ResolvedModelRoute,
    ) -> LLMProviderError:
        return LLMProviderError(
            code=(
                LLMErrorCode.UPSTREAM_TIMEOUT
                if timeout
                else LLMErrorCode.UPSTREAM_UNAVAILABLE
            ),
            provider=self.provider_name,
            model=resolved_route.gateway_alias,
            request_id=request.request_id,
            reason="gateway request failed",
            retryable=True,
            attempt=attempt,
            attribution=resolved_route.attribution,
        )

    @staticmethod
    def _terminal_error(error: LLMProviderError) -> LLMProviderError:
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
            attempts=error.attempts,
        )

    @staticmethod
    def _malformed_response(
        request: CompletionRequest,
        attempt: int,
        reason: str,
        resolved_route: ResolvedModelRoute,
    ) -> LLMProviderError:
        return LLMProviderError(
            code=LLMErrorCode.MALFORMED_RESPONSE,
            provider="litellm-gateway",
            model=resolved_route.gateway_alias,
            request_id=request.request_id,
            reason=reason[:_MAX_ERROR_TEXT],
            retryable=False,
            attempt=attempt,
            attribution=resolved_route.attribution,
        )

    @staticmethod
    def _stream_interrupted(
        request: CompletionRequest,
        attempt: int,
        partial_output: str,
        partial_tool_calls: tuple[dict[str, object], ...] = (),
        *,
        resolved_route: ResolvedModelRoute,
    ) -> LLMProviderError:
        return LLMProviderError(
            code=LLMErrorCode.STREAM_INTERRUPTED,
            provider="litellm-gateway",
            model=resolved_route.gateway_alias,
            request_id=request.request_id,
            reason="gateway stream ended after output was delivered",
            retryable=False,
            attempt=attempt,
            partial_output=partial_output,
            partial_tool_calls=partial_tool_calls,
            attribution=resolved_route.attribution,
        )

    def _should_retry(
        self,
        error: LLMProviderError,
        attempt: int,
        request_class: LLMRequestClass,
    ) -> bool:
        return error.retryable and attempt < self._config.attempts_for(request_class)

    def _sleep(self, attempt: int, error: LLMProviderError | None = None) -> None:
        delay = self._retry_delay(attempt, error)
        if delay > 0:
            time.sleep(delay)

    async def _async_sleep(
        self, attempt: int, error: LLMProviderError | None = None
    ) -> None:
        delay = self._retry_delay(attempt, error)
        if delay > 0:
            import asyncio

            await asyncio.sleep(delay)

    def _retry_delay(self, attempt: int, error: LLMProviderError | None) -> float:
        retry_after = error.retry_after_seconds if error is not None else None
        if retry_after is not None:
            return min(self._config.max_backoff_seconds, max(0.0, retry_after))
        exponential = self._config.backoff_seconds * (2 ** max(0, attempt - 1))
        capped = min(self._config.max_backoff_seconds, exponential)
        jitter = random.uniform(0.0, self._config.jitter_seconds)
        return min(self._config.max_backoff_seconds, capped + jitter)

    def _parse_completion(
        self,
        raw: object,
        request: CompletionRequest,
        attempt: int,
        resolved_route: ResolvedModelRoute,
        attribution: LLMAttribution | None,
        attempts: tuple[LLMAttempt, ...],
    ) -> CompletionResult:
        root = _mapping(raw)
        choices = _sequence(root.get("choices"))
        if not choices:
            raise self._malformed_response(
                request, attempt, "missing choices", resolved_route
            )
        first = _mapping(choices[0])
        message = _mapping(first.get("message"))
        usage = _usage(root.get("usage"))
        return CompletionResult(
            request_id=request.request_id,
            text=_content_text(message.get("content")),
            model=_string(root.get("model"), resolved_route.gateway_alias),
            finish_reason=_optional_string(first.get("finish_reason")),
            usage=usage,
            attempt=attempt,
            tool_calls=_tool_calls(message.get("tool_calls")),
            attribution=attribution or resolved_route.attribution,
            attempts=attempts,
        )

    def _stream_event_from_line(
        self,
        line: str,
        request: CompletionRequest,
        attempt: int,
        model: str,
        sequence: int,
        resolved_route: ResolvedModelRoute,
    ) -> StreamEvent | None:
        if not line.startswith("data:"):
            return None
        data = line[5:].strip()
        if data == "[DONE]":
            return StreamEvent(
                kind="completed",
                request_id=request.request_id,
                sequence=max(sequence + 1, 1),
                model=model,
                attempt=attempt,
                attribution=resolved_route.attribution,
            )
        raw: object = json.loads(data)
        root = _mapping(raw)
        choices = _sequence(root.get("choices"))
        if not choices:
            usage = _usage(root.get("usage"))
            if usage is not None:
                return StreamEvent(
                    kind="completed",
                    request_id=request.request_id,
                    sequence=max(sequence + 1, 1),
                    model=_string(root.get("model"), model),
                    usage=usage,
                    attempt=attempt,
                    attribution=resolved_route.attribution,
                )
            return None
        first = _mapping(choices[0])
        delta = _mapping(first.get("delta"))
        text = _content_text(delta.get("content"))
        tool_calls = _tool_calls(delta.get("tool_calls"))
        resolved_model = _string(root.get("model"), model)
        if not text and not tool_calls:
            usage = _usage(root.get("usage"))
            if usage is not None:
                return StreamEvent(
                    kind="completed",
                    request_id=request.request_id,
                    sequence=max(sequence + 1, 1),
                    model=resolved_model,
                    usage=usage,
                    attempt=attempt,
                    attribution=resolved_route.attribution,
                )
            return None
        return StreamEvent(
            kind="delta",
            request_id=request.request_id,
            sequence=sequence + 1,
            model=resolved_model,
            text=text,
            tool_calls=tool_calls,
            attempt=attempt,
            attribution=resolved_route.attribution,
        )


def _mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    raise ValueError("expected a JSON object")


def _sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, list | tuple):
        return tuple(value)
    raise ValueError("expected a JSON array")


def _string(value: object, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _safe_metadata_header(headers: Mapping[str, str], name: str) -> str | None:
    value = headers.get(name)
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > _MAX_METADATA_LENGTH:
        return None
    if any(ord(character) < 32 or ord(character) > 126 for character in normalized):
        return None
    return normalized


def _content_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            str(item.get("text", "")) for item in value if isinstance(item, Mapping)
        )
    return ""


def _tool_calls(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        cast(dict[str, object], item) for item in value if isinstance(item, Mapping)
    )


def _usage(value: object) -> Usage | None:
    if not isinstance(value, Mapping):
        return None
    return Usage(
        prompt_tokens=_int_or_none(value.get("prompt_tokens")),
        completion_tokens=_int_or_none(value.get("completion_tokens")),
        total_tokens=_int_or_none(value.get("total_tokens")),
    )


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    value = headers.get("retry-after")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())
