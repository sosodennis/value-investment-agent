from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import NoReturn, TypeVar
from uuid import uuid4

import httpx
from pydantic import BaseModel, TypeAdapter, ValidationError

from src.llm_provider.application.context import get_provider_principal
from src.llm_provider.domain.contracts import (
    CompletionRequest,
    CompletionResult,
    LLMErrorCode,
    LLMProviderError,
    LLMProviderPort,
    StreamEvent,
    StructuredRequest,
)
from src.llm_provider.domain.errors import ProviderSettingsError
from src.llm_provider.domain.provider_models import ManagedProviderKey, OpenRouterModel

_Model = TypeVar("_Model", bound=BaseModel)
_Value = TypeVar("_Value")


class _CompletionEnvelope(BaseModel):
    result: CompletionResult


class _StreamEnvelope(BaseModel):
    event: StreamEvent


class _SettingsEnvelope(BaseModel):
    result: dict[str, object]


def _malformed(request: CompletionRequest) -> NoReturn:
    raise LLMProviderError(
        code=LLMErrorCode.MALFORMED_RESPONSE,
        provider="llm-provider-service",
        model=request.route.alias,
        request_id=request.request_id,
        reason="provider service returned a malformed response",
        retryable=False,
    ) from None


def _settings_value(adapter: TypeAdapter[_Value], value: object) -> _Value:
    try:
        return adapter.validate_python(value)
    except ValidationError:
        raise ProviderSettingsError("provider_unavailable") from None


def _url() -> str:
    return os.getenv("LLM_PROVIDER_SERVICE_URL", "").strip().rstrip("/")


def _token() -> str:
    return os.getenv("LLM_PROVIDER_SERVICE_TOKEN", "").strip()


def _deadline(seconds: float) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=max(0.001, seconds))


def _context(*, user_id: str, seconds: float) -> dict[str, object]:
    return {
        "principal": {"subject_id": user_id},
        "correlation_id": str(uuid4()),
        "contract_version": "internal.v1",
        "deadline_at": _deadline(seconds).isoformat().replace("+00:00", "Z"),
    }


def _raise_provider_transport_error(
    request: CompletionRequest, error: httpx.TransportError
) -> NoReturn:
    timed_out = isinstance(error, httpx.TimeoutException)
    raise LLMProviderError(
        code=(
            LLMErrorCode.UPSTREAM_TIMEOUT
            if timed_out
            else LLMErrorCode.UPSTREAM_UNAVAILABLE
        ),
        provider="llm-provider-service",
        model=request.route.alias,
        request_id=request.request_id,
        reason=(
            "provider service request timed out"
            if timed_out
            else "provider service is unavailable"
        ),
        retryable=True,
    ) from None


class LLMProviderServiceClient(LLMProviderPort):
    def __init__(
        self, *, base_url: str | None = None, token: str | None = None
    ) -> None:
        self._base_url = (base_url or _url()).rstrip("/")
        self._token = token if token is not None else _token()
        if not self._base_url:
            raise RuntimeError("LLM_PROVIDER_SERVICE_URL is required")
        if not self._token:
            raise RuntimeError("LLM_PROVIDER_SERVICE_TOKEN is required")
        self._client = httpx.Client(timeout=None)
        self._async_client = httpx.AsyncClient(timeout=None)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def _principal(self) -> str:
        principal = get_provider_principal()
        if principal is None:
            raise LLMProviderError(
                code=LLMErrorCode.PROVIDER_CONTEXT_MISSING,
                provider="llm-provider-service",
                model="openrouter-default",
                request_id="unknown",
                reason="authenticated provider principal is required",
                retryable=False,
            )
        return principal.user_id

    @staticmethod
    def _input(
        request: CompletionRequest,
        *,
        response_schema: dict[str, object] | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": "llm.v1",
            "messages": [
                message.model_dump(mode="json") for message in request.messages
            ],
            "route": request.route.model_dump(mode="json"),
            "request_id": request.request_id,
            "operation": request.operation,
            "request_class": request.request_class.value,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "timeout_seconds": request.timeout_seconds,
            "idempotency_key": request.idempotency_key,
            "metadata": request.metadata,
            "tools": list(request.tools),
            "tool_choice": request.tool_choice,
        }
        if response_schema is not None:
            payload["response_schema"] = response_schema
        return payload

    @staticmethod
    def _result(
        response: httpx.Response, request: CompletionRequest
    ) -> CompletionResult:
        try:
            return _CompletionEnvelope.model_validate_json(response.content).result
        except ValidationError:
            _malformed(request)

    @staticmethod
    def _event(line: str, request: CompletionRequest) -> StreamEvent:
        try:
            return _StreamEnvelope.model_validate_json(line[6:]).event
        except ValidationError:
            _malformed(request)

    @classmethod
    def _raise_response(
        cls, response: httpx.Response, request: CompletionRequest
    ) -> None:
        try:
            body = response.json()
            error = body.get("error", {}) if isinstance(body, dict) else {}
            if not isinstance(error, dict):
                raise ValueError("invalid error envelope")
            code = str(error.get("code", "upstream_unavailable"))
            retryable = bool(error.get("retryable", response.status_code >= 500))
        except (ValueError, TypeError):
            code, retryable = (
                "upstream_unavailable",
                True,
            )
        if code == "deadline_exceeded":
            code = LLMErrorCode.UPSTREAM_TIMEOUT.value
        try:
            error_code = LLMErrorCode(code)
        except ValueError:
            error_code = LLMErrorCode.UPSTREAM_UNAVAILABLE
        raise LLMProviderError(
            code=error_code,
            provider="llm-provider-service",
            model=request.route.alias,
            request_id=request.request_id,
            reason="LLM provider service request failed",
            retryable=retryable,
            http_status=response.status_code,
        )

    def _post(
        self,
        request: CompletionRequest,
        *,
        response_schema: dict[str, object] | None = None,
    ) -> httpx.Response:
        try:
            return self._client.post(
                f"{self._base_url}/v1/completions",
                headers=self._headers(),
                json={
                    "context": _context(
                        user_id=self._principal(), seconds=request.timeout_seconds
                    ),
                    "input": self._input(request, response_schema=response_schema),
                },
                timeout=request.timeout_seconds,
            )
        except httpx.TransportError as exc:
            _raise_provider_transport_error(request, exc)

    async def _apost(
        self,
        request: CompletionRequest,
        *,
        response_schema: dict[str, object] | None = None,
    ) -> httpx.Response:
        try:
            return await self._async_client.post(
                f"{self._base_url}/v1/completions",
                headers=self._headers(),
                json={
                    "context": _context(
                        user_id=self._principal(), seconds=request.timeout_seconds
                    ),
                    "input": self._input(request, response_schema=response_schema),
                },
                timeout=request.timeout_seconds,
            )
        except httpx.TransportError as exc:
            _raise_provider_transport_error(request, exc)

    def complete(self, request: CompletionRequest) -> CompletionResult:
        response = self._post(request)
        if response.status_code >= 400:
            self._raise_response(response, request)
        return self._result(response, request)

    async def acomplete(self, request: CompletionRequest) -> CompletionResult:
        response = await self._apost(request)
        if response.status_code >= 400:
            self._raise_response(response, request)
        return self._result(response, request)

    def complete_structured(self, request: StructuredRequest[_Model]) -> _Model:
        response = self._post(
            request.completion,
            response_schema=request.response_schema.model_json_schema(),
        )
        if response.status_code >= 400:
            self._raise_response(response, request.completion)
        result = self._result(response, request.completion)
        return self._structured_result(request, result)

    async def acomplete_structured(self, request: StructuredRequest[_Model]) -> _Model:
        response = await self._apost(
            request.completion,
            response_schema=request.response_schema.model_json_schema(),
        )
        if response.status_code >= 400:
            self._raise_response(response, request.completion)
        result = self._result(response, request.completion)
        return self._structured_result(request, result)

    @staticmethod
    def _structured_result(
        request: StructuredRequest[_Model], result: CompletionResult
    ) -> _Model:
        try:
            return request.response_schema.model_validate_json(result.text)
        except ValidationError:
            raise LLMProviderError(
                code=LLMErrorCode.SCHEMA_VALIDATION_FAILED,
                provider="llm-provider-service",
                model=request.completion.route.alias,
                request_id=request.completion.request_id,
                reason="provider response did not match the requested schema",
                retryable=False,
            ) from None

    def stream(self, request: CompletionRequest) -> Iterator[StreamEvent]:
        yield from self._stream_sync(request)

    def _stream_sync(self, request: CompletionRequest) -> Iterator[StreamEvent]:
        try:
            with self._client.stream(
                "POST",
                f"{self._base_url}/v1/completions/stream",
                headers=self._headers(),
                json={
                    "context": _context(
                        user_id=self._principal(), seconds=request.timeout_seconds
                    ),
                    "input": self._input(request),
                },
                timeout=request.timeout_seconds,
            ) as response:
                if response.status_code >= 400:
                    response.read()
                    self._raise_response(response, request)
                for line in response.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    yield self._event(line, request)
        except httpx.TransportError as exc:
            _raise_provider_transport_error(request, exc)

    async def astream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        try:
            async with self._async_client.stream(
                "POST",
                f"{self._base_url}/v1/completions/stream",
                headers=self._headers(),
                json={
                    "context": _context(
                        user_id=self._principal(), seconds=request.timeout_seconds
                    ),
                    "input": self._input(request),
                },
                timeout=request.timeout_seconds,
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    self._raise_response(response, request)
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        yield self._event(line, request)
        except httpx.TransportError as exc:
            _raise_provider_transport_error(request, exc)

    async def aclose(self) -> None:
        self._client.close()
        await self._async_client.aclose()


class LLMProviderServiceSettingsClient:
    def __init__(
        self, *, base_url: str | None = None, token: str | None = None
    ) -> None:
        self._base_url = (base_url or _url()).rstrip("/")
        self._token = token if token is not None else _token()
        if not self._base_url:
            raise RuntimeError("LLM_PROVIDER_SERVICE_URL is required")
        if not self._token:
            raise RuntimeError("LLM_PROVIDER_SERVICE_TOKEN is required")
        self._client = httpx.AsyncClient(timeout=None)

    async def _call(
        self, action: str, payload: dict[str, object], *, user_id: str
    ) -> dict[str, object]:
        try:
            response = await self._client.post(
                f"{self._base_url}{action}",
                headers={"Authorization": f"Bearer {self._token}"},
                json={
                    "context": _context(user_id=user_id, seconds=10.0),
                    "input": payload,
                },
                timeout=10.0,
            )
        except httpx.TransportError:
            raise ProviderSettingsError("provider_unavailable") from None
        if response.status_code >= 400:
            raise ProviderSettingsError(
                "not_found" if response.status_code == 404 else "provider_unavailable"
            )
        try:
            return _SettingsEnvelope.model_validate_json(response.content).result
        except ValidationError:
            raise ProviderSettingsError("provider_unavailable") from None

    async def list_keys(self, *, user_id: str) -> list[ManagedProviderKey]:
        result = await self._call("/v1/provider-keys/list", {}, user_id=user_id)
        return _settings_value(
            TypeAdapter(list[ManagedProviderKey]), result.get("keys")
        )

    async def add_key(
        self, *, user_id: str, key: str, label: str
    ) -> ManagedProviderKey:
        result = await self._call(
            "/v1/provider-keys/create",
            {"api_key": key, "label": label},
            user_id=user_id,
        )
        return _settings_value(TypeAdapter(ManagedProviderKey), result.get("key"))

    async def replace_key(
        self, *, user_id: str, key_id: str, key: str, label: str
    ) -> ManagedProviderKey:
        result = await self._call(
            "/v1/provider-keys/replace",
            {"key_id": key_id, "api_key": key, "label": label},
            user_id=user_id,
        )
        return _settings_value(TypeAdapter(ManagedProviderKey), result.get("key"))

    async def test_key(self, *, user_id: str, key_id: str) -> bool:
        result = await self._call(
            "/v1/provider-keys/test", {"key_id": key_id}, user_id=user_id
        )
        try:
            return TypeAdapter(bool).validate_python(result.get("passed"), strict=True)
        except ValidationError:
            raise ProviderSettingsError("provider_unavailable") from None

    async def delete_key(self, *, user_id: str, key_id: str) -> None:
        await self._call(
            "/v1/provider-keys/delete", {"key_id": key_id}, user_id=user_id
        )

    async def selected_model_settings(
        self, *, user_id: str | None = None
    ) -> tuple[str, list[OpenRouterModel]]:
        result = await self._call(
            "/v1/settings/read", {}, user_id=user_id or self._principal()
        )
        return _settings_value(
            TypeAdapter(str), result.get("selected_model")
        ), _settings_value(TypeAdapter(list[OpenRouterModel]), result.get("models"))

    async def update_selected_model(self, *, model_id: str, user_id: str) -> str:
        result = await self._call(
            "/v1/settings/update", {"selected_model": model_id}, user_id=user_id
        )
        return _settings_value(TypeAdapter(str), result.get("selected_model"))

    def _principal(self) -> str:
        principal = get_provider_principal()
        if principal is None:
            raise ProviderSettingsError("provider_context_missing")
        return principal.user_id

    async def aclose(self) -> None:
        await self._client.aclose()
