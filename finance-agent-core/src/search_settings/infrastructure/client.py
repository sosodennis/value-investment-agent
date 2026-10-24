from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Literal, TypeVar
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field, ValidationError

from src.search_settings.domain import (
    ProviderCapabilities,
    ProviderKeyResult,
    ProviderPreference,
    SearchSettingsSnapshot,
    StrictModel,
)

T = TypeVar("T", bound=BaseModel)


class SearchServiceError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class _Context(StrictModel):
    subject_id: str = Field(min_length=1, max_length=256)


class _RequestContext(StrictModel):
    principal: _Context
    correlation_id: str = Field(min_length=1, max_length=128)
    contract_version: Literal["internal.v1"] = "internal.v1"
    deadline_at: str


class _Envelope(StrictModel):
    context: _RequestContext
    input: dict[str, object]


class _Error(StrictModel):
    code: str
    message: str
    retryable: bool
    retry_after_ms: int | None = None


class _ErrorEnvelope(StrictModel):
    contract_version: Literal["internal.v1"]
    correlation_id: str
    error: _Error


class _ProviderCatalog(StrictModel):
    providers: list[ProviderCapabilities]


class _CatalogResult(StrictModel):
    catalog: _ProviderCatalog


class _CatalogEnvelope(StrictModel):
    contract_version: Literal["internal.v1"]
    correlation_id: str
    result: _CatalogResult


class _SettingsResult(StrictModel):
    settings: SearchSettingsSnapshot


class _SettingsEnvelope(StrictModel):
    contract_version: Literal["internal.v1"]
    correlation_id: str
    result: _SettingsResult


class _KeyEnvelope(StrictModel):
    contract_version: Literal["internal.v1"]
    correlation_id: str
    result: ProviderKeyResult


class SearchServiceClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = (
            base_url if base_url is not None else os.getenv("SEARCH_SERVICE_URL", "")
        ).rstrip("/")
        self._token = (
            token
            if token is not None
            else os.getenv("SEARCH_SERVICE_TOKEN", "").strip()
        )
        if not self._base_url or not self._token:
            raise RuntimeError(
                "SEARCH_SERVICE_URL and SEARCH_SERVICE_TOKEN are required"
            )
        self._client = client or httpx.AsyncClient(timeout=10.0)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    def _deadline() -> str:
        return (
            (datetime.now(UTC) + timedelta(seconds=10))
            .isoformat()
            .replace("+00:00", "Z")
        )

    async def _post(
        self,
        *,
        principal: str,
        path: str,
        input_data: dict[str, object],
        response_type: type[T],
    ) -> T:
        payload = _Envelope(
            context=_RequestContext(
                principal=_Context(subject_id=principal),
                correlation_id=str(uuid4()),
                deadline_at=self._deadline(),
            ),
            input=input_data,
        )
        try:
            response = await self._client.post(
                f"{self._base_url}{path}",
                json=payload.model_dump(mode="json"),
                headers={"Authorization": f"Bearer {self._token}"},
            )
        except httpx.TimeoutException:
            raise SearchServiceError(
                503, "service_unavailable", "Search Service timed out"
            ) from None
        except httpx.TransportError:
            raise SearchServiceError(
                503, "service_unavailable", "Search Service is unavailable"
            ) from None
        if response.is_error:
            try:
                error = _ErrorEnvelope.model_validate(response.json()).error
            except (ValidationError, ValueError):
                raise SearchServiceError(
                    503, "service_unavailable", "Search Service is unavailable"
                ) from None
            raise SearchServiceError(response.status_code, error.code, error.message)
        try:
            return response_type.model_validate(response.json())
        except (ValidationError, ValueError):
            raise SearchServiceError(
                502,
                "invalid_service_response",
                "Search Service returned an invalid response",
            ) from None

    async def read(
        self, *, principal: str
    ) -> tuple[list[ProviderCapabilities], SearchSettingsSnapshot]:
        catalog, settings = (
            await self._catalog(principal),
            await self._settings(principal),
        )
        return catalog, settings

    async def catalog(self, *, principal: str) -> list[ProviderCapabilities]:
        return await self._catalog(principal)

    async def _catalog(self, principal: str) -> list[ProviderCapabilities]:
        envelope = await self._post(
            principal=principal,
            path="/v1/providers/catalog",
            input_data={},
            response_type=_CatalogEnvelope,
        )
        return envelope.result.catalog.providers

    async def _settings(self, principal: str) -> SearchSettingsSnapshot:
        envelope = await self._post(
            principal=principal,
            path="/v1/settings/read",
            input_data={},
            response_type=_SettingsEnvelope,
        )
        return envelope.result.settings

    async def update(
        self, *, principal: str, providers: list[ProviderPreference]
    ) -> SearchSettingsSnapshot:
        envelope = await self._post(
            principal=principal,
            path="/v1/settings/update",
            input_data={
                "providers": [item.model_dump(mode="json") for item in providers]
            },
            response_type=_SettingsEnvelope,
        )
        return envelope.result.settings

    async def add_key(
        self, *, principal: str, provider: str, api_key: str, label: str
    ) -> ProviderKeyResult:
        envelope = await self._post(
            principal=principal,
            path="/v1/provider-keys/add",
            input_data={"provider": provider, "api_key": api_key, "label": label},
            response_type=_KeyEnvelope,
        )
        return envelope.result

    async def replace_key(
        self, *, principal: str, key_id: str, provider: str, api_key: str, label: str
    ) -> ProviderKeyResult:
        envelope = await self._post(
            principal=principal,
            path="/v1/provider-keys/replace",
            input_data={
                "key_id": key_id,
                "provider": provider,
                "api_key": api_key,
                "label": label,
            },
            response_type=_KeyEnvelope,
        )
        return envelope.result

    async def delete_key(self, *, principal: str, key_id: str) -> None:
        await self._post(
            principal=principal,
            path="/v1/provider-keys/delete",
            input_data={"key_id": key_id},
            response_type=_DeleteEnvelope,
        )


class _DeleteResult(StrictModel):
    deleted: bool


class _DeleteEnvelope(StrictModel):
    contract_version: Literal["internal.v1"]
    correlation_id: str
    result: _DeleteResult
