from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from search_service.app import create_app
from search_service.contracts import (
    Operation,
    ProviderCapabilities,
    ProviderKeySummary,
    SearchResult,
)


@dataclass
class Credential:
    provider: str
    api_key: str
    enabled: bool = True
    priority: int = 0


class FakeProvider:
    def __init__(self, name: str, *, capabilities: ProviderCapabilities) -> None:
        self.name = name
        self.capabilities = capabilities
        self.calls: list[tuple[str, str]] = []
        self.tested: list[str] = []
        self.test_result = True
        self.results: tuple[SearchResult, ...] = (
            SearchResult(
                title="Example",
                canonical_url="https://example.test/article",
                snippet="snippet",
                provider=name,
            ),
        )

    async def search(self, *, operation, request, api_key, deadline_at):
        self.calls.append((operation.value, api_key))
        return self.results

    async def test_key(self, api_key: str, *, deadline_at):
        self.tested.append(api_key)
        return self.test_result


class FakeControlPlane:
    def __init__(self, credentials: tuple[Credential, ...] = ()) -> None:
        self.credentials = credentials
        self.keys: list[ProviderKeySummary] = []
        self.raw_keys: list[str] = []

    async def credentials_for(self, *, subject_id: str):
        return self.credentials

    async def add_tested_key(
        self, *, subject_id, provider, api_key, label, suffix, fingerprint
    ):
        self.raw_keys.append(api_key)
        summary = ProviderKeySummary(
            provider=provider,
            label=label,
            suffix=suffix,
            fingerprint=fingerprint,
            enabled=True,
            priority=0,
        )
        self.keys.append(summary)
        return summary

    async def list_keys(self, *, subject_id):
        return tuple(self.keys)

    async def delete_key(self, *, subject_id, provider):
        self.keys = [key for key in self.keys if key.provider != provider]

    async def update_provider(self, *, subject_id, provider, enabled, priority):
        _ = (subject_id, provider, enabled, priority)


def context(*, user_id: str = "user-a") -> dict[str, object]:
    return {
        "principal": {"subject_id": user_id},
        "correlation_id": "corr-122",
        "contract_version": "internal.v1",
        "deadline_at": (datetime.now(UTC) + timedelta(seconds=3)).isoformat(),
    }


def client_for(
    control_plane: FakeControlPlane,
    providers: dict[str, FakeProvider],
) -> httpx.AsyncClient:
    app = create_app(
        providers=providers, control_plane=control_plane, token="service-token"
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://search.test"
    )


@pytest.mark.asyncio
async def test_authentication_precedes_principal_use() -> None:
    provider = FakeProvider(
        "alpha",
        capabilities=ProviderCapabilities(operations=frozenset({Operation.WEB})),
    )
    control = FakeControlPlane((Credential("alpha", "alpha-secret"),))
    client = client_for(control, {"alpha": provider})
    try:
        response = await client.post(
            "/v1/search/web",
            headers={"Authorization": "Bearer wrong"},
            json={"context": {"principal": {"subject_id": ""}}, "input": {}},
        )
    finally:
        await client.aclose()
    assert response.status_code == 401
    assert provider.calls == []


@pytest.mark.asyncio
async def test_priority_skips_disabled_and_missing_key() -> None:
    first = FakeProvider(
        "first",
        capabilities=ProviderCapabilities(operations=frozenset({Operation.WEB})),
    )
    second = FakeProvider(
        "second",
        capabilities=ProviderCapabilities(operations=frozenset({Operation.WEB})),
    )
    control = FakeControlPlane(
        (
            Credential("first", "", enabled=True, priority=0),
            Credential("second", "second-secret", enabled=True, priority=2),
        )
    )
    client = client_for(control, {"first": first, "second": second})
    try:
        response = await client.post(
            "/v1/search/web",
            headers={"Authorization": "Bearer service-token"},
            json={"context": context(), "input": {"query": "value"}},
        )
    finally:
        await client.aclose()
    assert response.status_code == 200
    assert first.calls == []
    assert second.calls == [("web", "second-secret")]


@pytest.mark.asyncio
async def test_unsupported_options_and_empty_success() -> None:
    provider = FakeProvider(
        "alpha",
        capabilities=ProviderCapabilities(
            operations=frozenset({Operation.WEB}), optional_fields=frozenset()
        ),
    )
    control = FakeControlPlane((Credential("alpha", "secret"),))
    client = client_for(control, {"alpha": provider})
    try:
        unsupported = await client.post(
            "/v1/search/web",
            headers={"Authorization": "Bearer service-token"},
            json={"context": context(), "input": {"query": "value", "region": "US"}},
        )
    finally:
        await client.aclose()
    assert unsupported.status_code == 422
    assert unsupported.json()["error"]["code"] == "UNSUPPORTED_CAPABILITY"


@pytest.mark.asyncio
async def test_empty_search_is_success_with_correlation_and_version() -> None:
    provider = FakeProvider(
        "alpha",
        capabilities=ProviderCapabilities(operations=frozenset({Operation.NEWS})),
    )
    provider.results = ()
    control = FakeControlPlane((Credential("alpha", "secret"),))
    client = client_for(control, {"alpha": provider})
    try:
        response = await client.post(
            "/v1/search/news",
            headers={"Authorization": "Bearer service-token"},
            json={"context": context(), "input": {"query": "earnings"}},
        )
    finally:
        await client.aclose()
    assert response.status_code == 200
    assert response.json()["results"] == []
    assert response.json()["correlation_id"] == "corr-122"
    assert response.json()["schema_version"] == "search.v1"


@pytest.mark.asyncio
async def test_key_test_failure_does_not_persist_and_success_redacts() -> None:
    provider = FakeProvider(
        "alpha",
        capabilities=ProviderCapabilities(operations=frozenset({Operation.WEB})),
    )
    provider.test_result = False
    control = FakeControlPlane()
    client = client_for(control, {"alpha": provider})
    try:
        failed = await client.post(
            "/v1/provider-keys/alpha/add",
            headers={"Authorization": "Bearer service-token"},
            json={
                "context": context(),
                "input": {"api_key": "raw-secret", "label": "main"},
            },
        )
        assert failed.status_code == 422
        assert control.keys == []
        provider.test_result = True
        success = await client.post(
            "/v1/provider-keys/alpha/add",
            headers={"Authorization": "Bearer service-token"},
            json={
                "context": context(),
                "input": {"api_key": "raw-secret", "label": "main"},
            },
        )
    finally:
        await client.aclose()
    assert success.status_code == 200
    assert "raw-secret" not in success.text
    assert control.raw_keys == ["raw-secret"]
