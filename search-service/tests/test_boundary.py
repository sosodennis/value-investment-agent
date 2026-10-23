from __future__ import annotations

import asyncio
import json
import runpy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Never

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from src.shared.internal_services import InternalErrorResponse
from test_contract import (
    Credential,
    FakeControlPlane,
    FakeProvider,
    client_for,
    context,
)

from search_service import contracts
from search_service.contracts import (
    Capability,
    Operation,
    ProviderCapabilities,
    ProviderKeySummary,
    SearchErrorCode,
    SearchRequestBase,
    SearchResult,
)
from search_service.errors import SearchServiceError

HEADERS = {"Authorization": "Bearer service-token"}
KEY_INPUT = {"provider": "alpha", "api_key": "raw-secret", "label": "main"}
CONTROL_ROUTES = (
    ("/v1/search/web", {"query": "private query"}),
    ("/v1/search/news", {"query": "private query"}),
    ("/v1/settings/read", {}),
    (
        "/v1/settings/update",
        {"providers": [{"provider": "alpha", "enabled": True, "priority": 0}]},
    ),
    ("/v1/provider-keys/add", KEY_INPUT),
    ("/v1/provider-keys/replace", {**KEY_INPUT, "key_id": "key-123"}),
    ("/v1/provider-keys/list", {}),
    ("/v1/provider-keys/delete", {"key_id": "key-123"}),
)


def provider() -> FakeProvider:
    return FakeProvider(
        "alpha",
        capabilities=ProviderCapabilities(
            provider="alpha",
            operations=frozenset(Operation),
            optional_fields=frozenset(Capability),
        ),
    )


class UnavailableControlPlane(FakeControlPlane):
    def __init__(self, outcome: str) -> None:
        super().__init__()
        self.outcome = outcome
        self.cancelled = False

    async def fail(self, **_values: object) -> Never:
        if self.outcome == "deadline":
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled = True
        if self.outcome == "typed":
            raise SearchServiceError(
                SearchErrorCode.RATE_LIMITED,
                429,
                "control plane rate limited",
                True,
                17,
            )
        raise RuntimeError("raw-secret private query internal-storage-url")

    credentials_for = fail
    get_settings = fail
    replace_settings = fail
    add_tested_key = fail
    replace_tested_key = fail
    list_keys = fail
    delete_key = fail


def validate_openapi_response(
    artifact: dict[str, object],
    route: str,
    status: int,
    response_body: object,
) -> None:
    paths = artifact["paths"]
    response = paths[route]["post"]["responses"][str(status)]
    response_schema = response["content"]["application/json"]["schema"]
    schema = {
        "$ref": response_schema["$ref"],
        "components": artifact["components"],
    }
    Draft202012Validator(schema).validate(response_body)


@pytest.mark.asyncio
@pytest.mark.parametrize(("route", "operation_input"), CONTROL_ROUTES)
@pytest.mark.parametrize("outcome", ("unexpected", "typed", "deadline"))
async def test_control_plane_errors_are_bounded_and_redacted(
    route: str, operation_input: dict[str, object], outcome: str
) -> None:
    control = UnavailableControlPlane(outcome)
    request_context = context()
    if outcome == "deadline":
        request_context["deadline_at"] = (
            datetime.now(UTC) + timedelta(milliseconds=25)
        ).isoformat()
    async with client_for(control, {"alpha": provider()}) as client:
        response = await client.post(
            route,
            headers=HEADERS,
            json={"context": request_context, "input": operation_input},
        )
    expected_status, expected_code = {
        "unexpected": (503, "UPSTREAM_UNAVAILABLE"),
        "typed": (429, "RATE_LIMITED"),
        "deadline": (504, "DEADLINE_EXCEEDED"),
    }[outcome]
    assert response.status_code == expected_status
    artifact = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "contracts/search-service-openapi.json"
        ).read_text()
    )
    validate_openapi_response(artifact, route, expected_status, response.json())
    body = InternalErrorResponse.model_validate(response.json())
    assert (body.correlation_id, body.contract_version, body.error.code) == (
        "corr-122",
        "internal.v1",
        expected_code,
    )
    assert body.error.retryable is True
    if outcome == "typed":
        assert body.error.retry_after_ms == 17
    if outcome == "deadline":
        assert control.cancelled is True
    assert "raw-secret" not in response.text
    assert "private query" not in response.text
    assert "internal-storage-url" not in response.text


def test_openapi_response_validator_rejects_a_malformed_success_wrapper() -> None:
    artifact = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "contracts/search-service-openapi.json"
        ).read_text()
    )
    with pytest.raises(JsonSchemaValidationError):
        validate_openapi_response(
            artifact, "/v1/providers/catalog", 200, {"providers": []}
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "route", ("/v1/providers/catalog", "/v1/settings/read", "/v1/provider-keys/list")
)
async def test_empty_input_routes_reject_extra_fields(route: str) -> None:
    async with client_for(FakeControlPlane(), {"alpha": provider()}) as client:
        response = await client.post(
            route,
            headers=HEADERS,
            json={"context": context(), "input": {"user_id": "another-owner"}},
        )
    assert response.status_code == 400
    body = InternalErrorResponse.model_validate(response.json())
    assert body.error.code == "INVALID_REQUEST"
    assert body.correlation_id == "corr-122"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "route,operation_input",
    (
        ("/v1/providers/catalog", {}),
        *CONTROL_ROUTES,
        ("/v1/provider-keys/test", {"provider": "alpha", "api_key": "raw-secret"}),
    ),
)
async def test_actual_success_response_matches_committed_openapi(
    route: str, operation_input: dict[str, object]
) -> None:
    root = Path(__file__).resolve().parents[2]
    artifact = json.loads((root / "contracts/search-service-openapi.json").read_text())
    generated = runpy.run_path(str(root / "search-service/scripts/generate_openapi.py"))
    assert artifact == generated["document"]()
    control = FakeControlPlane((Credential("alpha", "secret"),))
    async with client_for(control, {"alpha": provider()}) as client:
        response = await client.post(
            route,
            headers=HEADERS,
            json={"context": context(), "input": operation_input},
        )
    assert response.status_code == 200
    validate_openapi_response(artifact, route, 200, response.json())
    reference = artifact["paths"][route]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    schema_name = reference.rsplit("/", 1)[1]
    model = getattr(contracts, schema_name)
    model.model_validate(response.json())
    assert set(response.json()) == {"correlation_id", "contract_version", "result"}
    assert "raw-secret" not in response.text


@pytest.mark.parametrize(
    "published_at", ("2026-10-23T18:30:00", "2026-10-23T18:30:00+08:00")
)
def test_publication_time_rejects_naive_and_non_utc_values(published_at: str) -> None:
    with pytest.raises(ValueError, match="UTC RFC3339"):
        SearchResult(
            title="News",
            canonical_url="https://example.test",
            provider="alpha",
            published_at=published_at,
        )


def test_publication_time_accepts_utc_rfc3339() -> None:
    result = SearchResult(
        title="News",
        canonical_url="https://example.test",
        provider="alpha",
        published_at="2026-10-23T18:30:00Z",
    )
    assert result.model_dump(mode="json")["published_at"] == "2026-10-23T18:30:00Z"


class FailedProvider(FakeProvider):
    def __init__(self, error: SearchServiceError) -> None:
        super().__init__("alpha", capabilities=provider().capabilities)
        self.error = error

    async def search(
        self,
        *,
        operation: Operation,
        request: SearchRequestBase,
        api_key: str,
        deadline_at: datetime,
    ) -> tuple[SearchResult, ...]:
        self.calls.append((operation.value, api_key))
        raise self.error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    (
        SearchServiceError(
            SearchErrorCode.RATE_LIMITED, 429, "provider rate limited", True, 33
        ),
        SearchServiceError(
            SearchErrorCode.UPSTREAM_MALFORMED,
            502,
            "provider response could not be normalized",
        ),
    ),
)
async def test_provider_error_mapping_and_fallback(error: SearchServiceError) -> None:
    failed = FailedProvider(error)
    control = FakeControlPlane((Credential("alpha", "secret"),))
    async with client_for(control, {"alpha": failed}) as client:
        response = await client.post(
            "/v1/search/web",
            headers=HEADERS,
            json={"context": context(), "input": {"query": "private query"}},
        )
    assert response.status_code == error.status_code
    body = InternalErrorResponse.model_validate(response.json())
    assert body.error.code == error.code
    assert body.error.retry_after_ms == error.retry_after_ms
    fallback = provider()
    fallback.name = "beta"
    control.credentials = (
        Credential("alpha", "secret"),
        Credential("beta", "fallback", priority=1),
    )
    async with client_for(control, {"alpha": failed, "beta": fallback}) as client:
        response = await client.post(
            "/v1/search/web",
            headers=HEADERS,
            json={"context": context(), "input": {"query": "private query"}},
        )
    assert response.status_code == 200
    assert fallback.calls == [("web", "fallback")]


@pytest.mark.asyncio
async def test_failed_replacement_preserves_existing_key() -> None:
    control = FakeControlPlane()
    upstream = provider()
    async with client_for(control, {"alpha": upstream}) as client:
        added = await client.post(
            "/v1/provider-keys/add",
            headers=HEADERS,
            json={"context": context(), "input": KEY_INPUT},
        )
        assert added.status_code == 200
        original = tuple(control.keys)
        upstream.test_result = False
        tested = await client.post(
            "/v1/provider-keys/test",
            headers=HEADERS,
            json={
                "context": context(),
                "input": {"provider": "alpha", "api_key": "bad-secret"},
            },
        )
        assert tested.status_code == 200
        assert tested.json()["result"] == {
            "provider": "alpha",
            "valid": False,
            "status": "invalid",
        }
        rejected = await client.post(
            "/v1/provider-keys/replace",
            headers=HEADERS,
            json={
                "context": context(),
                "input": {**KEY_INPUT, "key_id": "key-123", "api_key": "bad-secret"},
            },
        )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "AUTHENTICATION_FAILED"
    assert tuple(control.keys) == original
    assert control.raw_keys == ["raw-secret"]
    assert "bad-secret" not in rejected.text


class OwnedControlPlane(FakeControlPlane):
    def __init__(self) -> None:
        super().__init__()
        self.owned = {
            ("user-a", "key-123"): ProviderKeySummary(
                id="key-123",
                provider="alpha",
                label="main",
                suffix="cret",
                fingerprint="masked",
                enabled=True,
                priority=0,
            )
        }

    async def delete_key(self, *, subject_id: str, key_id: str) -> None:
        self.owned.pop((subject_id, key_id), None)

    async def list_keys(self, *, subject_id: str) -> tuple[ProviderKeySummary, ...]:
        return tuple(
            key for (owner, _key_id), key in self.owned.items() if owner == subject_id
        )

    async def credentials_for(self, *, subject_id: str) -> tuple[Credential, ...]:
        return (Credential("alpha", f"{subject_id}-secret"),)


@pytest.mark.asyncio
async def test_delete_is_owner_scoped_and_idempotent() -> None:
    control = OwnedControlPlane()
    async with client_for(control, {}) as client:
        foreign = await client.post(
            "/v1/provider-keys/delete",
            headers=HEADERS,
            json={"context": context(user_id="user-b"), "input": {"key_id": "key-123"}},
        )
        absent = await client.post(
            "/v1/provider-keys/delete",
            headers=HEADERS,
            json={"context": context(user_id="user-b"), "input": {"key_id": "missing"}},
        )
        assert foreign.json() == absent.json()
        assert ("user-a", "key-123") in control.owned
        first = await client.post(
            "/v1/provider-keys/delete",
            headers=HEADERS,
            json={"context": context(), "input": {"key_id": "key-123"}},
        )
        repeated = await client.post(
            "/v1/provider-keys/delete",
            headers=HEADERS,
            json={"context": context(), "input": {"key_id": "key-123"}},
        )
    assert first.status_code == repeated.status_code == 200
    assert first.json() == repeated.json()
    assert control.owned == {}


@pytest.mark.asyncio
async def test_key_listing_and_search_routing_use_the_context_owner() -> None:
    control = OwnedControlPlane()
    upstream = provider()
    async with client_for(control, {"alpha": upstream}) as client:
        own = await client.post(
            "/v1/provider-keys/list",
            headers=HEADERS,
            json={"context": context(), "input": {}},
        )
        other = await client.post(
            "/v1/provider-keys/list",
            headers=HEADERS,
            json={"context": context(user_id="user-b"), "input": {}},
        )
        for owner in ("user-a", "user-b"):
            response = await client.post(
                "/v1/search/web",
                headers=HEADERS,
                json={
                    "context": context(user_id=owner),
                    "input": {"query": "private query"},
                },
            )
            assert response.status_code == 200
    assert own.json()["result"]["providers"][0]["id"] == "key-123"
    assert other.json()["result"]["providers"] == []
    assert upstream.calls == [("web", "user-a-secret"), ("web", "user-b-secret")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "route,operation_input",
    (
        ("/v1/providers/catalog", {}),
        *CONTROL_ROUTES,
        ("/v1/provider-keys/test", {"provider": "alpha", "api_key": "raw-secret"}),
    ),
)
@pytest.mark.parametrize(
    "invalid", ("extra-envelope-field", "non-object-input", "expired")
)
async def test_every_operation_rejects_invalid_envelopes_and_expired_deadlines(
    route: str, operation_input: dict[str, object], invalid: str
) -> None:
    request_context = context()
    body: dict[str, object] = {"context": request_context, "input": operation_input}
    if invalid == "extra-envelope-field":
        body["user_id"] = "another-owner"
    elif invalid == "non-object-input":
        body["input"] = []
    else:
        request_context["deadline_at"] = (
            datetime.now(UTC) - timedelta(seconds=1)
        ).isoformat()
    async with client_for(FakeControlPlane(), {"alpha": provider()}) as client:
        response = await client.post(route, headers=HEADERS, json=body)
    assert response.status_code == (504 if invalid == "expired" else 400)
    error = InternalErrorResponse.model_validate(response.json())
    assert error.correlation_id == "corr-122"
    assert error.error.code == (
        "DEADLINE_EXCEEDED" if invalid == "expired" else "INVALID_REQUEST"
    )


def test_error_status_mapping_matches_the_frozen_finite_set() -> None:
    expected = {
        "INVALID_REQUEST": 400,
        "UNSUPPORTED_CAPABILITY": 422,
        "AUTHENTICATION_FAILED": 422,
        "RATE_LIMITED": 429,
        "DEADLINE_EXCEEDED": 504,
        "UPSTREAM_UNAVAILABLE": 503,
        "UPSTREAM_MALFORMED": 502,
    }
    artifact = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "contracts/search-service-openapi.json"
        ).read_text()
    )
    assert set(SearchErrorCode) == set(expected)
    assert artifact["x-search-error-status-mappings"] == expected
    for path in artifact["paths"].values():
        if "post" in path:
            assert {str(status) for status in expected.values()} <= set(
                path["post"]["responses"]
            )


@pytest.mark.asyncio
async def test_unconfigured_readiness_is_separate_from_liveness() -> None:
    async with client_for(FakeControlPlane(), {}) as client:
        assert (await client.get("/livez")).status_code == 200
        ready = await client.get("/readyz")
    assert ready.status_code == 503
    assert ready.json() == {"status": "not_ready", "contract_version": "internal.v1"}
