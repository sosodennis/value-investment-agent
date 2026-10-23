from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import NoReturn, TypeVar
from uuid import uuid4

import httpx
from pydantic import BaseModel

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
        payload: dict[str, object], request: CompletionRequest
    ) -> CompletionResult:
        result = payload.get("result")
        if not isinstance(result, dict):
            raise LLMProviderError(
                code=LLMErrorCode.MALFORMED_RESPONSE,
                provider="llm-provider-service",
                model=request.route.alias,
                request_id=request.request_id,
                reason="provider service returned a malformed response",
                retryable=False,
            )
        return CompletionResult.model_validate(result)

    @classmethod
    def _raise_response(
        cls, response: httpx.Response, request: CompletionRequest
    ) -> None:
        try:
            body = response.json()
            error = body.get("error", {}) if isinstance(body, dict) else {}
            code = str(error.get("code", "upstream_unavailable"))
            message = str(error.get("message", "LLM provider service request failed"))[
                :512
            ]
            retryable = bool(error.get("retryable", response.status_code >= 500))
        except (ValueError, TypeError):
            code, message, retryable = (
                "upstream_unavailable",
                "LLM provider service request failed",
                True,
            )
        try:
            error_code = LLMErrorCode(code)
        except ValueError:
            error_code = LLMErrorCode.UPSTREAM_UNAVAILABLE
        raise LLMProviderError(
            code=error_code,
            provider="llm-provider-service",
            model=request.route.alias,
            request_id=request.request_id,
            reason=message,
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
        return self._result(response.json(), request)

    async def acomplete(self, request: CompletionRequest) -> CompletionResult:
        response = await self._apost(request)
        if response.status_code >= 400:
            self._raise_response(response, request)
        return self._result(response.json(), request)

    def complete_structured(self, request: StructuredRequest[_Model]) -> _Model:
        response = self._post(
            request.completion,
            response_schema=request.response_schema.model_json_schema(),
        )
        if response.status_code >= 400:
            self._raise_response(response, request.completion)
        result = self._result(response.json(), request.completion)
        return request.response_schema.model_validate_json(result.text)

    async def acomplete_structured(self, request: StructuredRequest[_Model]) -> _Model:
        response = await self._apost(
            request.completion,
            response_schema=request.response_schema.model_json_schema(),
        )
        if response.status_code >= 400:
            self._raise_response(response, request.completion)
        result = self._result(response.json(), request.completion)
        return request.response_schema.model_validate_json(result.text)

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
                    self._raise_response(response, request)
                for line in response.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    yield StreamEvent.model_validate(json.loads(line[6:])["event"])
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
                    self._raise_response(response, request)
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        yield StreamEvent.model_validate(json.loads(line[6:])["event"])
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
        body = response.json()
        result = body.get("result") if isinstance(body, dict) else None
        if not isinstance(result, dict):
            raise ProviderSettingsError("provider_unavailable")
        return result

    async def list_keys(self, *, user_id: str) -> list[ManagedProviderKey]:
        result = await self._call("/v1/provider-keys/list", {}, user_id=user_id)
        return [_managed_key(item) for item in result.get("keys", [])]

    async def add_key(
        self, *, user_id: str, key: str, label: str
    ) -> ManagedProviderKey:
        result = await self._call(
            "/v1/provider-keys/create",
            {"api_key": key, "label": label},
            user_id=user_id,
        )
        return _managed_key(result["key"])

    async def replace_key(
        self, *, user_id: str, key_id: str, key: str, label: str
    ) -> ManagedProviderKey:
        result = await self._call(
            "/v1/provider-keys/replace",
            {"key_id": key_id, "api_key": key, "label": label},
            user_id=user_id,
        )
        return _managed_key(result["key"])

    async def test_key(self, *, user_id: str, key_id: str) -> bool:
        result = await self._call(
            "/v1/provider-keys/test", {"key_id": key_id}, user_id=user_id
        )
        return bool(result.get("passed"))

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
        return str(result["selected_model"]), [
            _model(item) for item in result.get("models", [])
        ]

    async def update_selected_model(self, *, model_id: str, user_id: str) -> str:
        result = await self._call(
            "/v1/settings/update", {"selected_model": model_id}, user_id=user_id
        )
        return str(result["selected_model"])

    def _principal(self) -> str:
        principal = get_provider_principal()
        if principal is None:
            raise ProviderSettingsError("provider_context_missing")
        return principal.user_id

    async def aclose(self) -> None:
        await self._client.aclose()


def _managed_key(item: object) -> ManagedProviderKey:
    if not isinstance(item, dict):
        raise ProviderSettingsError("provider_unavailable")
    return ManagedProviderKey(
        id=str(item.get("id", "")),
        label=str(item.get("label", "OpenRouter key")),
        suffix=str(item.get("suffix", "****")),
        fingerprint=str(item.get("fingerprint", "unknown")),
        created_at=item.get("created_at")
        if isinstance(item.get("created_at"), str)
        else None,
        status=str(item.get("status", "untested")),
        last_tested_at=item.get("last_tested_at")
        if isinstance(item.get("last_tested_at"), str)
        else None,
        failure_count=int(item.get("failure_count", 0)),
        cooldown_until=item.get("cooldown_until")
        if isinstance(item.get("cooldown_until"), str)
        else None,
        last_error=item.get("last_error")
        if isinstance(item.get("last_error"), str)
        else None,
        last_used_at=item.get("last_used_at")
        if isinstance(item.get("last_used_at"), str)
        else None,
        replacement_retire_at=item.get("replacement_retire_at")
        if isinstance(item.get("replacement_retire_at"), str)
        else None,
    )


def _model(item: object) -> OpenRouterModel:
    if not isinstance(item, dict):
        raise ProviderSettingsError("provider_unavailable")
    return OpenRouterModel(
        id=str(item.get("id", "")),
        name=str(item.get("name", "")),
        description=item.get("description")
        if isinstance(item.get("description"), str)
        else None,
        context_length=int(item["context_length"])
        if isinstance(item.get("context_length"), int)
        else None,
    )
