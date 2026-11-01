from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from src.shared.internal_services import InternalPrincipal, build_internal_context

from search_service.app import create_app
from search_service.contracts import (
    Capability,
    NewsSearchRequest,
    Operation,
    ProviderCapabilities,
    ProviderKeySetEnabledInput,
    ProviderKeySummary,
    ProviderSetting,
    SearchResult,
    UserSettings,
    WebSearchRequest,
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
        self.requests = []
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
        self.requests.append(request)
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
        _ = subject_id
        self.raw_keys.append(api_key)
        summary = ProviderKeySummary(
            id="key-123",
            provider=provider,
            label=label,
            suffix=suffix,
            fingerprint=fingerprint,
            enabled=True,
            priority=0,
        )
        self.keys.append(summary)
        return summary

    async def replace_tested_key(
        self, *, subject_id, provider, api_key, label, suffix, fingerprint, key_id
    ):
        _ = (subject_id, key_id)
        self.raw_keys.append(api_key)
        summary = ProviderKeySummary(
            id=key_id,
            provider=provider,
            label=label,
            suffix=suffix,
            fingerprint=fingerprint,
            enabled=True,
            priority=0,
        )
        self.keys = [summary]
        return summary

    async def list_keys(self, *, subject_id):
        return tuple(self.keys)

    async def delete_key(self, *, subject_id, key_id):
        _ = (subject_id, key_id)
        self.keys.clear()

    async def set_key_enabled(self, *, subject_id, key_id, enabled):
        _ = subject_id
        for index, key in enumerate(self.keys):
            if key.id == key_id:
                updated = key.model_copy(
                    update={
                        "enabled": enabled,
                        "status": "active" if enabled else "disabled",
                    }
                )
                self.keys[index] = updated
                return updated
        raise AssertionError("unknown key")

    async def get_settings(self, *, subject_id):
        _ = subject_id
        return UserSettings(providers=())

    async def replace_settings(self, *, subject_id, providers):
        _ = subject_id
        return UserSettings(
            providers=tuple(
                ProviderSetting(**provider.model_dump()) for provider in providers
            )
        )


def context(
    *, user_id: str = "user-a", deadline: datetime | None = None
) -> dict[str, object]:
    deadline = deadline or datetime.now(UTC) + timedelta(seconds=3)
    return build_internal_context(
        principal=InternalPrincipal(
            subject_id=user_id,
            organization_id="organization-122",
            membership_id="membership-122",
        ),
        correlation_id="corr-122",
        deadline_at=deadline,
        audience="search-service",
        signing_key="service-token",
        issued_at=deadline - timedelta(seconds=5),
    ).model_dump(mode="json")


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


def test_request_defaults_and_openapi_artifact_are_explicit() -> None:
    web = WebSearchRequest(query=" earnings ")
    news = NewsSearchRequest(query=" earnings ")
    assert (web.query, web.result_limit, web.timeout_seconds, web.safe_search) == (
        "earnings",
        10,
        30,
        True,
    )
    assert (news.result_limit, news.timeout_seconds, news.safe_search) == (20, 30, True)
    artifact = (
        Path(__file__).resolve().parents[2]
        / "contracts"
        / "search-service-openapi.json"
    )
    openapi = json.loads(artifact.read_text())
    assert set(openapi["paths"]) >= {
        "/v1/search/web",
        "/v1/search/news",
        "/v1/providers/catalog",
        "/v1/settings/read",
        "/v1/settings/update",
        "/v1/provider-keys/test",
        "/v1/provider-keys/add",
        "/v1/provider-keys/replace",
        "/v1/provider-keys/delete",
        "/v1/provider-keys/list",
    }
    schemas = openapi["components"]["schemas"]
    assert schemas["WebSearchRequest"]["properties"]["result_limit"]["default"] == 10
    assert schemas["NewsSearchRequest"]["properties"]["result_limit"]["default"] == 20
    assert schemas["WebSearchRequest"]["properties"]["timeout_seconds"]["maximum"] == 60
    assert (
        "worldwide"
        in schemas["WebSearchRequest"]["properties"]["region"]["anyOf"][0]["pattern"]
    )
    delete_schema = openapi["paths"]["/v1/provider-keys/delete"]["post"]["requestBody"][
        "content"
    ]["application/json"]["schema"]["$ref"]
    assert delete_schema.endswith("ProviderKeyDeleteEnvelope")
    error_schema = openapi["paths"]["/v1/search/web"]["post"]["responses"]["502"][
        "content"
    ]["application/json"]["schema"]["$ref"]
    assert error_schema.endswith("InternalErrorResponse")


def test_region_accepts_intent_and_script_locales_but_rejects_arbitrary_values() -> (
    None
):
    intent_lookup = WebSearchRequest(
        query="company ticker",
        region="en-US",
        time_range="year",
        result_limit=7,
        safe_search=True,
    )
    news_lookup = NewsSearchRequest(
        query="company news",
        region="worldwide",
        time_range="week",
        result_limit=8,
        safe_search=False,
    )
    script_locale = WebSearchRequest(query="test", region="zh-Hant-TW")
    assert intent_lookup.region == "en-US"
    assert news_lookup.region == "worldwide"
    assert script_locale.region == "zh-Hant-TW"
    with pytest.raises(ValueError):
        WebSearchRequest(query="test", region="not_a_region")


def test_provider_settings_model_a_key_pool_and_safe_usage_metadata() -> None:
    used_at = datetime.now(UTC)
    key = ProviderKeySummary(
        id="key-1",
        provider="alpha",
        label="primary",
        suffix="1234",
        fingerprint="sha256:masked",
        enabled=True,
        priority=0,
        last_used_at=used_at,
    )
    setting = ProviderSetting(provider="alpha", enabled=True, priority=0, keys=(key,))
    assert setting.keys == (key,)
    assert setting.model_dump(mode="json")["keys"][0]["last_used_at"]
    assert ProviderKeySetEnabledInput(key_id="key-1", enabled=False).enabled is False


@pytest.mark.asyncio
async def test_authentication_precedes_principal_use() -> None:
    provider = FakeProvider(
        "alpha",
        capabilities=ProviderCapabilities(
            provider="alpha", operations=frozenset({Operation.WEB})
        ),
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
    assert response.json()["error"]["code"] == "internal_auth_invalid"
    assert provider.calls == []


@pytest.mark.asyncio
async def test_authentication_failures_keep_internal_contract_codes() -> None:
    control = FakeControlPlane()
    app = create_app(providers={}, control_plane=control, token=None)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://search.test"
    )
    try:
        unconfigured = await client.post(
            "/v1/settings/read", json={"context": {}, "input": {}}
        )
    finally:
        await client.aclose()
    assert unconfigured.status_code == 401
    assert unconfigured.json()["error"]["code"] == "internal_auth_unconfigured"

    client = client_for(control, {})
    try:
        missing = await client.post(
            "/v1/settings/read", json={"context": {}, "input": {}}
        )
    finally:
        await client.aclose()
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "internal_auth_missing"


@pytest.mark.asyncio
async def test_priority_skips_disabled_and_missing_key() -> None:
    first = FakeProvider(
        "first",
        capabilities=ProviderCapabilities(
            provider="first",
            operations=frozenset({Operation.WEB}),
            optional_fields=frozenset({Capability.SAFE_SEARCH}),
        ),
    )
    second = FakeProvider(
        "second",
        capabilities=ProviderCapabilities(
            provider="second",
            operations=frozenset({Operation.WEB}),
            optional_fields=frozenset({Capability.SAFE_SEARCH}),
        ),
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
            provider="alpha",
            operations=frozenset({Operation.WEB}),
            optional_fields=frozenset(),
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
        capabilities=ProviderCapabilities(
            provider="alpha",
            operations=frozenset({Operation.NEWS}),
            optional_fields=frozenset({Capability.SAFE_SEARCH}),
        ),
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
    assert response.json()["result"]["results"] == []
    assert response.json()["correlation_id"] == "corr-122"
    assert response.json()["contract_version"] == "internal.v1"


@pytest.mark.asyncio
async def test_search_limit_and_worldwide_options_reach_provider() -> None:
    provider = FakeProvider(
        "alpha",
        capabilities=ProviderCapabilities(
            provider="alpha",
            operations=frozenset({Operation.NEWS}),
            optional_fields=frozenset(
                {Capability.REGION, Capability.SAFE_SEARCH, Capability.TIME_RANGE}
            ),
        ),
    )
    control = FakeControlPlane((Credential("alpha", "secret"),))
    client = client_for(control, {"alpha": provider})
    try:
        response = await client.post(
            "/v1/search/news",
            headers={"Authorization": "Bearer service-token"},
            json={
                "context": context(),
                "input": {
                    "query": "earnings",
                    "result_limit": 8,
                    "region": "worldwide",
                    "time_range": "week",
                    "safe_search": False,
                },
            },
        )
    finally:
        await client.aclose()
    assert response.status_code == 200
    sent = provider.requests[0]
    assert (sent.result_limit, sent.region, sent.time_range, sent.safe_search) == (
        8,
        "worldwide",
        "week",
        False,
    )


@pytest.mark.asyncio
async def test_key_test_failure_does_not_persist_and_success_redacts() -> None:
    provider = FakeProvider(
        "alpha",
        capabilities=ProviderCapabilities(
            provider="alpha", operations=frozenset({Operation.WEB})
        ),
    )
    provider.test_result = False
    control = FakeControlPlane()
    client = client_for(control, {"alpha": provider})
    try:
        failed = await client.post(
            "/v1/provider-keys/add",
            headers={"Authorization": "Bearer service-token"},
            json={
                "context": context(),
                "input": {
                    "provider": "alpha",
                    "api_key": "raw-secret",
                    "label": "main",
                },
            },
        )
        assert failed.status_code == 422
        assert control.keys == []
        provider.test_result = True
        success = await client.post(
            "/v1/provider-keys/add",
            headers={"Authorization": "Bearer service-token"},
            json={
                "context": context(),
                "input": {
                    "provider": "alpha",
                    "api_key": "raw-secret",
                    "label": "main",
                },
            },
        )
    finally:
        await client.aclose()
    assert success.status_code == 200
    assert "raw-secret" not in success.text
    assert control.raw_keys == ["raw-secret"]


@pytest.mark.asyncio
async def test_delete_key_uses_owned_id_without_key_material() -> None:
    control = FakeControlPlane()
    client = client_for(control, {})
    try:
        response = await client.post(
            "/v1/provider-keys/delete",
            headers={"Authorization": "Bearer service-token"},
            json={"context": context(), "input": {"key_id": "key-123"}},
        )
    finally:
        await client.aclose()
    assert response.status_code == 200
    assert response.json()["result"] == {"deleted": True}
