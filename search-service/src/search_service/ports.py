from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .contracts import (
    Capability,
    Operation,
    ProviderCapabilities,
    ProviderKeySummary,
    SearchRequestBase,
    SearchResult,
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
    provider: str
    api_key: str
    enabled: bool
    priority: int


class SearchControlPlane(Protocol):
    """Durable owner-scoped state; implementations must be shared across replicas."""

    async def credentials_for(
        self, *, subject_id: str
    ) -> tuple[ProviderCredential, ...]: ...

    async def add_tested_key(
        self,
        *,
        subject_id: str,
        provider: str,
        api_key: str,
        label: str,
        suffix: str,
        fingerprint: str,
    ) -> ProviderKeySummary: ...

    async def replace_tested_key(
        self,
        *,
        subject_id: str,
        provider: str,
        api_key: str,
        label: str,
        suffix: str,
        fingerprint: str,
    ) -> ProviderKeySummary: ...

    async def list_keys(self, *, subject_id: str) -> tuple[ProviderKeySummary, ...]: ...

    async def delete_key(self, *, subject_id: str, provider: str) -> None: ...

    async def update_provider(
        self,
        *,
        subject_id: str,
        provider: str,
        enabled: bool,
        priority: int,
    ) -> None: ...


def requested_capabilities(request: SearchRequestBase) -> frozenset[Capability]:
    fields: set[Capability] = set()
    if request.region is not None:
        fields.add(Capability.REGION)
    if request.time_range is not None:
        fields.add(Capability.TIME_RANGE)
    if request.safe_search is not None:
        fields.add(Capability.SAFE_SEARCH)
    return frozenset(fields)
