from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Literal, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from src.search_settings.domain import (
    ProviderCapabilities,
    ProviderKeyResult,
    ProviderPreference,
    SearchSettingsSnapshot,
    StrictModel,
)
from src.shared.internal_services import InternalPrincipal, build_internal_context
from src.shared.kernel.correlation import resolve_correlation_id

T = TypeVar("T", bound=BaseModel)


class SearchServiceError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class _Envelope(StrictModel):
    context: dict[str, object]
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
        organization_id: str | None = None,
        membership_id: str | None = None,
    ) -> T:
        correlation_id = resolve_correlation_id()
        payload = _Envelope(
            context=build_internal_context(
                principal=InternalPrincipal(
                    subject_id=principal,
                    organization_id=organization_id or "unscoped",
                    membership_id=membership_id or "unscoped",
                ),
                correlation_id=correlation_id,
                deadline_at=datetime.now(UTC) + timedelta(seconds=10),
                audience="search-service",
                signing_key=self._token,
            ).model_dump(mode="json"),
            input=input_data,
        )
        try:
            headers = {"Authorization": f"Bearer {self._token}"}
            headers["X-Request-ID"] = correlation_id
            response = await self._client.post(
                f"{self._base_url}{path}",
                json=payload.model_dump(mode="json"),
                headers=headers,
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
                envelope = _ErrorEnvelope.model_validate(response.json())
                if envelope.correlation_id != correlation_id:
                    raise ValueError("search service correlation mismatch")
                error = envelope.error
            except (ValidationError, ValueError):
                raise SearchServiceError(
                    503, "service_unavailable", "Search Service is unavailable"
                ) from None
            raise SearchServiceError(response.status_code, error.code, error.message)
        try:
            envelope = response_type.model_validate(response.json())
        except (ValidationError, ValueError):
            raise SearchServiceError(
                502,
                "invalid_service_response",
                "Search Service returned an invalid response",
            ) from None
        if getattr(envelope, "correlation_id", None) != correlation_id:
            raise SearchServiceError(
                502,
                "invalid_service_response",
                "Search Service returned an invalid response",
            )
        return envelope

    async def read(
        self,
        *,
        principal: str,
        organization_id: str | None = None,
        membership_id: str | None = None,
    ) -> tuple[list[ProviderCapabilities], SearchSettingsSnapshot]:
        catalog, settings = (
            await self._catalog(principal, organization_id, membership_id),
            await self._settings(principal, organization_id, membership_id),
        )
        return catalog, settings

    async def catalog(
        self,
        *,
        principal: str,
        organization_id: str | None = None,
        membership_id: str | None = None,
    ) -> list[ProviderCapabilities]:
        return await self._catalog(principal, organization_id, membership_id)

    async def _catalog(
        self,
        principal: str,
        organization_id: str | None,
        membership_id: str | None,
    ) -> list[ProviderCapabilities]:
        envelope = await self._post(
            principal=principal,
            path="/v1/providers/catalog",
            input_data={},
            response_type=_CatalogEnvelope,
            organization_id=organization_id,
            membership_id=membership_id,
        )
        return envelope.result.catalog.providers

    async def _settings(
        self,
        principal: str,
        organization_id: str | None,
        membership_id: str | None,
    ) -> SearchSettingsSnapshot:
        envelope = await self._post(
            principal=principal,
            path="/v1/settings/read",
            input_data={},
            response_type=_SettingsEnvelope,
            organization_id=organization_id,
            membership_id=membership_id,
        )
        return envelope.result.settings

    async def update(
        self,
        *,
        principal: str,
        providers: list[ProviderPreference],
        organization_id: str | None = None,
        membership_id: str | None = None,
    ) -> SearchSettingsSnapshot:
        envelope = await self._post(
            principal=principal,
            path="/v1/settings/update",
            input_data={
                "providers": [item.model_dump(mode="json") for item in providers]
            },
            response_type=_SettingsEnvelope,
            organization_id=organization_id,
            membership_id=membership_id,
        )
        return envelope.result.settings

    async def add_key(
        self,
        *,
        principal: str,
        provider: str,
        api_key: str,
        label: str,
        organization_id: str | None = None,
        membership_id: str | None = None,
    ) -> ProviderKeyResult:
        envelope = await self._post(
            principal=principal,
            path="/v1/provider-keys/add",
            input_data={"provider": provider, "api_key": api_key, "label": label},
            response_type=_KeyEnvelope,
            organization_id=organization_id,
            membership_id=membership_id,
        )
        return envelope.result

    async def replace_key(
        self,
        *,
        principal: str,
        key_id: str,
        provider: str,
        api_key: str,
        label: str,
        organization_id: str | None = None,
        membership_id: str | None = None,
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
            organization_id=organization_id,
            membership_id=membership_id,
        )
        return envelope.result

    async def delete_key(
        self,
        *,
        principal: str,
        key_id: str,
        organization_id: str | None = None,
        membership_id: str | None = None,
    ) -> None:
        await self._post(
            principal=principal,
            path="/v1/provider-keys/delete",
            input_data={"key_id": key_id},
            response_type=_DeleteEnvelope,
            organization_id=organization_id,
            membership_id=membership_id,
        )

    async def set_key_enabled(
        self,
        *,
        principal: str,
        key_id: str,
        enabled: bool,
        organization_id: str | None = None,
        membership_id: str | None = None,
    ) -> ProviderKeyResult:
        envelope = await self._post(
            principal=principal,
            path="/v1/provider-keys/set-enabled",
            input_data={"key_id": key_id, "enabled": enabled},
            response_type=_KeyEnvelope,
            organization_id=organization_id,
            membership_id=membership_id,
        )
        return envelope.result


class _DeleteResult(StrictModel):
    deleted: bool


class _DeleteEnvelope(StrictModel):
    contract_version: Literal["internal.v1"]
    correlation_id: str
    result: _DeleteResult
