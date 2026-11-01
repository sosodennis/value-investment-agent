from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from src.shared.internal_services import InternalPrincipal, build_internal_context

from search_service.app import create_app
from search_service.contracts import (
    Capability,
    Operation,
    ProviderCapabilities,
    SearchErrorCode,
    SearchResult,
)
from search_service.errors import SearchServiceError


def _context() -> dict[str, object]:
    deadline = datetime.now(UTC) + timedelta(seconds=2)
    return build_internal_context(
        principal=InternalPrincipal(
            subject_id="runtime-user",
            organization_id="organization-runtime",
            membership_id="membership-runtime",
        ),
        correlation_id="runtime-correlation",
        deadline_at=deadline,
        audience="search-service",
        signing_key="runtime-service-token",
        issued_at=deadline - timedelta(seconds=5),
    ).model_dump(mode="json")


@dataclass
class Credential:
    key_id: str
    provider: str
    api_key: str
    priority: int
    enabled: bool = True
    status: str = "active"
    leased: bool = False


@dataclass
class Pool:
    credentials: list[Credential]
    failures: list[tuple[str, str]] = field(default_factory=list)
    provider_failures: list[str] = field(default_factory=list)
    releases: list[tuple[str, bool]] = field(default_factory=list)

    async def credentials_for(self, *, organization_id: str) -> tuple[Credential, ...]:
        _ = organization_id
        return tuple(self.credentials)

    async def claim_credential(
        self, *, organization_id: str, provider: str, lease_seconds: int = 30
    ) -> Credential | None:
        _ = (organization_id, lease_seconds)
        for credential in sorted(self.credentials, key=lambda item: item.priority):
            if (
                credential.provider == provider
                and credential.enabled
                and credential.status == "active"
                and not credential.leased
            ):
                credential.leased = True
                return credential
        return None

    async def release_credential(
        self, *, organization_id: str, key_id: str, succeeded: bool = False
    ) -> None:
        _ = organization_id
        credential = next(item for item in self.credentials if item.key_id == key_id)
        credential.leased = False
        self.releases.append((key_id, succeeded))

    async def record_key_failure(
        self,
        *,
        organization_id: str,
        key_id: str,
        status: str = "cooldown",
        cooldown_seconds: int = 30,
    ) -> None:
        _ = (organization_id, cooldown_seconds)
        credential = next(item for item in self.credentials if item.key_id == key_id)
        credential.status = status
        self.failures.append((key_id, status))

    async def record_provider_failure(
        self, *, organization_id: str, provider: str, cooldown_seconds: int = 30
    ) -> None:
        _ = (organization_id, cooldown_seconds)
        self.provider_failures.append(provider)


class LeaseBusyPool(Pool):
    async def claim_credential(
        self, *, organization_id: str, provider: str, lease_seconds: int = 30
    ) -> Credential | None:
        _ = (organization_id, provider, lease_seconds)
        return None


class ScriptedProvider:
    def __init__(
        self,
        name: str,
        outcomes: dict[str, tuple[SearchResult, ...] | SearchServiceError],
    ) -> None:
        self.name = name
        self.capabilities = ProviderCapabilities(
            provider=name,
            operations=frozenset({Operation.WEB}),
            optional_fields=frozenset({Capability.SAFE_SEARCH}),
        )
        self.outcomes = outcomes
        self.calls: list[str] = []

    async def search(self, *, operation, request, api_key, deadline_at):
        _ = (operation, request, deadline_at)
        self.calls.append(api_key)
        outcome = self.outcomes[api_key]
        if isinstance(outcome, SearchServiceError):
            raise outcome
        return outcome

    async def test_key(self, api_key: str, *, deadline_at):
        _ = (api_key, deadline_at)
        return True


def _result(provider: str) -> tuple[SearchResult, ...]:
    return (
        SearchResult(
            title="Result",
            canonical_url="https://example.test/result",
            provider=provider,
        ),
    )


def _client(pool: Pool, providers: dict[str, ScriptedProvider]) -> httpx.AsyncClient:
    app = create_app(
        providers=providers, control_plane=pool, token="runtime-service-token"
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://runtime.test"
    )


@pytest.mark.asyncio
async def test_does_not_use_snapshot_credential_when_lease_claim_is_unavailable() -> (
    None
):
    provider = ScriptedProvider("primary", {"primary-key": _result("primary")})
    pool = LeaseBusyPool(
        [Credential("primary-id", "primary", "primary-key", priority=0)]
    )
    client = _client(pool, {"primary": provider})
    try:
        response = await client.post(
            "/v1/search/web",
            headers={"Authorization": "Bearer runtime-service-token"},
            json={"context": _context(), "input": {"query": "earnings"}},
        )
    finally:
        await client.aclose()
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"
    assert provider.calls == []


@pytest.mark.asyncio
async def test_rotates_keys_within_provider_before_falling_back() -> None:
    first = SearchServiceError(
        SearchErrorCode.AUTHENTICATION_FAILED, 422, "provider key was rejected"
    )
    provider = ScriptedProvider(
        "tavily", {"key-one": first, "key-two": _result("tavily")}
    )
    pool = Pool(
        [
            Credential("id-one", "tavily", "key-one", priority=0),
            Credential("id-two", "tavily", "key-two", priority=1),
        ]
    )
    client = _client(pool, {"tavily": provider})
    try:
        response = await client.post(
            "/v1/search/web",
            headers={"Authorization": "Bearer runtime-service-token"},
            json={"context": _context(), "input": {"query": "earnings"}},
        )
    finally:
        await client.aclose()
    assert response.status_code == 200
    assert provider.calls == ["key-one", "key-two"]
    assert pool.failures == [("id-one", "invalid")]
    assert pool.releases == [("id-one", False), ("id-two", True)]


@pytest.mark.asyncio
async def test_falls_back_to_next_provider_after_key_failure() -> None:
    unavailable = SearchServiceError(
        SearchErrorCode.UPSTREAM_UNAVAILABLE, 503, "provider unavailable", True
    )
    primary = ScriptedProvider("primary", {"primary-key": unavailable})
    fallback = ScriptedProvider("fallback", {"fallback-key": _result("fallback")})
    pool = Pool(
        [
            Credential("primary-id", "primary", "primary-key", priority=0),
            Credential("fallback-id", "fallback", "fallback-key", priority=1),
        ]
    )
    client = _client(pool, {"primary": primary, "fallback": fallback})
    try:
        response = await client.post(
            "/v1/search/web",
            headers={"Authorization": "Bearer runtime-service-token"},
            json={"context": _context(), "input": {"query": "earnings"}},
        )
    finally:
        await client.aclose()
    assert response.status_code == 200
    assert primary.calls == ["primary-key"]
    assert fallback.calls == ["fallback-key"]


@pytest.mark.asyncio
async def test_provider_failure_opens_circuit_without_exhausting_key_pool() -> None:
    unavailable = SearchServiceError(
        SearchErrorCode.UPSTREAM_UNAVAILABLE, 503, "provider unavailable", True
    )
    primary = ScriptedProvider(
        "primary",
        {"primary-one": unavailable, "primary-two": unavailable},
    )
    fallback = ScriptedProvider("fallback", {"fallback-key": _result("fallback")})
    pool = Pool(
        [
            Credential("primary-one-id", "primary", "primary-one", priority=0),
            Credential("primary-two-id", "primary", "primary-two", priority=1),
            Credential("fallback-id", "fallback", "fallback-key", priority=2),
        ]
    )
    client = _client(pool, {"primary": primary, "fallback": fallback})
    try:
        response = await client.post(
            "/v1/search/web",
            headers={"Authorization": "Bearer runtime-service-token"},
            json={"context": _context(), "input": {"query": "earnings"}},
        )
    finally:
        await client.aclose()
    assert response.status_code == 200
    assert primary.calls == ["primary-one"]
    assert pool.provider_failures == ["primary"]
    assert fallback.calls == ["fallback-key"]


@pytest.mark.asyncio
async def test_empty_results_are_success_and_total_attempts_are_bounded() -> None:
    unavailable = SearchServiceError(
        SearchErrorCode.UPSTREAM_UNAVAILABLE, 503, "provider unavailable", True
    )
    primary = ScriptedProvider(
        "primary",
        {"key-one": (), "key-two": unavailable, "key-three": unavailable},
    )
    fallback = ScriptedProvider("fallback", {"fallback-key": _result("fallback")})
    pool = Pool(
        [
            Credential("one", "primary", "key-one", priority=0),
            Credential("two", "primary", "key-two", priority=1),
            Credential("three", "primary", "key-three", priority=2),
            Credential("four", "fallback", "fallback-key", priority=3),
        ]
    )
    client = _client(pool, {"primary": primary, "fallback": fallback})
    try:
        response = await client.post(
            "/v1/search/web",
            headers={"Authorization": "Bearer runtime-service-token"},
            json={"context": _context(), "input": {"query": "earnings"}},
        )
    finally:
        await client.aclose()
    assert response.status_code == 200
    assert primary.calls == ["key-one"]
    assert fallback.calls == []
    assert response.json()["result"]["results"] == []
