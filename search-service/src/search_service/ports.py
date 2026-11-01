from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .contracts import (
    Capability,
    Operation,
    ProviderCapabilities,
    ProviderKeySummary,
    ProviderPreference,
    SearchRequestBase,
    SearchResult,
    UserSettings,
)


class SearchProvider(Protocol):
    name: str
    capabilities: ProviderCapabilities

    async def search(
        self,
        *,
        operation: Operation,
        request: SearchRequestBase,
        api_key: str,
        deadline_at: datetime,
    ) -> tuple[SearchResult, ...]: ...

    async def test_key(self, api_key: str, *, deadline_at: datetime) -> bool: ...


class ProviderCredential(Protocol):
    key_id: str
    provider: str
    api_key: str
    enabled: bool
    priority: int
    provider_priority: int
    key_priority: int
    fingerprint: str
    status: str
    cooldown_until: datetime | None


class SearchControlPlane(Protocol):
    """Durable organization-scoped state; implementations must be shared across replicas."""

    async def credentials_for(
        self, *, organization_id: str
    ) -> tuple[ProviderCredential, ...]: ...

    async def claim_credential(
        self, *, organization_id: str, provider: str, lease_seconds: int = 30
    ) -> ProviderCredential | None: ...

    async def release_credential(
        self, *, organization_id: str, key_id: str, succeeded: bool = False
    ) -> None: ...

    async def record_key_failure(
        self,
        *,
        organization_id: str,
        key_id: str,
        status: str = "cooldown",
        cooldown_seconds: int = 30,
    ) -> None: ...

    async def record_provider_failure(
        self,
        *,
        organization_id: str,
        provider: str,
        cooldown_seconds: int = 30,
    ) -> None: ...

    async def set_key_enabled(
        self, *, organization_id: str, key_id: str, enabled: bool
    ) -> ProviderKeySummary: ...

    async def add_tested_key(
        self,
        *,
        organization_id: str,
        provider: str,
        api_key: str,
        label: str,
        suffix: str,
        fingerprint: str,
    ) -> ProviderKeySummary: ...

    async def replace_tested_key(
        self,
        *,
        organization_id: str,
        provider: str,
        api_key: str,
        label: str,
        suffix: str,
        fingerprint: str,
        key_id: str,
    ) -> ProviderKeySummary: ...

    async def list_keys(
        self, *, organization_id: str
    ) -> tuple[ProviderKeySummary, ...]: ...

    async def delete_key(self, *, organization_id: str, key_id: str) -> None: ...

    async def get_settings(self, *, organization_id: str) -> UserSettings: ...

    async def replace_settings(
        self, *, organization_id: str, providers: tuple[ProviderPreference, ...]
    ) -> UserSettings: ...


def requested_capabilities(request: SearchRequestBase) -> frozenset[Capability]:
    fields: set[Capability] = set()
    if request.region is not None:
        fields.add(Capability.REGION)
    if request.time_range is not None:
        fields.add(Capability.TIME_RANGE)
    if request.safe_search is not None:
        fields.add(Capability.SAFE_SEARCH)
    return frozenset(fields)
