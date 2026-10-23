from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
from src.llm_provider_service.domain.key_metadata import key_fingerprint
from src.llm_provider_service.domain.routes import user_route_alias
from src.llm_provider_service.infrastructure.litellm_admin import (
    MANAGED_MARKER,
    LiteLLMAdminClient,
    LiteLLMAdminError,
)


def _model_info(
    model_id: str,
    *,
    fingerprint: str = "fingerprint-1",
    status: str = "healthy",
    last_error: str | None = None,
    replacement_retire_at: str | None = None,
) -> dict[str, object]:
    return {
        "model_info": {
            "id": model_id,
            MANAGED_MARKER: True,
            "label": "Personal key",
            "suffix": "1234",
            "fingerprint": fingerprint,
            "status": status,
            "last_error": last_error,
            "replacement_retire_at": replacement_retire_at,
        }
    }


def _admin_client(
    handler: httpx.MockTransport,
) -> tuple[LiteLLMAdminClient, httpx.AsyncClient]:
    http_client = httpx.AsyncClient(transport=handler, base_url="http://gateway.test")
    admin = LiteLLMAdminClient(
        base_url="http://gateway.test/v1/",
        admin_token="admin-token",
        openrouter_headers={"HTTP-Referer": "https://app.test"},
        http_client=http_client,
    )
    return admin, http_client


@pytest.mark.asyncio
async def test_listing_keeps_managed_keys_and_sanitizes_lifecycle_metadata() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "model_info": {
                            "id": "managed-healthy",
                            MANAGED_MARKER: True,
                            "status": "healthy",
                            "last_error": "invalid_key",
                            "failure_count": 3,
                        }
                    },
                    {
                        "model_info": {
                            "id": "managed-unsafe",
                            MANAGED_MARKER: True,
                            "status": "credential-leak",
                            "last_error": "sk-upstream-secret",
                            "failure_count": -2,
                        }
                    },
                    {"model_info": {"id": "foreign", MANAGED_MARKER: False}},
                ]
            },
        )

    admin, http_client = _admin_client(httpx.MockTransport(handler))
    try:
        keys = await admin.list_managed()
    finally:
        await http_client.aclose()

    assert [key.id for key in keys] == ["managed-healthy", "managed-unsafe"]
    assert keys[0].status == "healthy"
    assert keys[0].last_error == "invalid_key"
    assert keys[0].failure_count == 3
    assert keys[1].status == "untested"
    assert keys[1].last_error is None
    assert keys[1].failure_count == 0
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].url == "http://gateway.test/model/info"
    assert requests[0].headers["Authorization"] == "Bearer admin-token"


@pytest.mark.asyncio
async def test_key_add_uses_user_pool_and_owned_ids_for_duplicate_resolution() -> None:
    secret = "sk-openrouter-private-value"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/model/info":
            return httpx.Response(
                200,
                json={
                    "data": [
                        _model_info(
                            "other-users-key", fingerprint=key_fingerprint(secret)
                        )
                    ]
                },
            )
        if request.url.path == "/model/new":
            return httpx.Response(200, json={"data": {"model_id": "new-key-id"}})
        raise AssertionError(f"unexpected management route: {request.url.path}")

    admin, http_client = _admin_client(httpx.MockTransport(handler))
    try:
        key = await admin.add_key(
            key=secret,
            label="Alice's key",
            model="openai/gpt-4o-mini",
            model_name=user_route_alias("alice"),
            existing_ids=set(),
        )
    finally:
        await http_client.aclose()

    assert key.id == "new-key-id"
    assert key.fingerprint == key_fingerprint(secret)
    assert len(requests) == 2
    create_request = requests[1]
    assert create_request.method == "POST"
    assert create_request.url == "http://gateway.test/model/new"
    assert create_request.headers["Authorization"] == "Bearer admin-token"
    body = json.loads(create_request.content)
    assert body["model_name"] == user_route_alias("alice")
    params = body["litellm_params"]
    assert params["model"] == "openrouter/openai/gpt-4o-mini"
    assert params["api_base"] == "https://openrouter.ai/api/v1"
    assert params["api_key"] == secret
    assert params["headers"] == {"HTTP-Referer": "https://app.test"}
    metadata = body["model_info"]
    assert metadata[MANAGED_MARKER] is True
    assert metadata["fingerprint"] == key_fingerprint(secret)
    assert metadata["suffix"] == secret[-4:]
    assert secret not in repr(key)


@pytest.mark.asyncio
async def test_health_and_replacement_lifecycle_update_only_managed_records() -> None:
    requests: list[httpx.Request] = []
    records = [
        _model_info("healthy-key", status="cooldown", last_error="rate_limited"),
        _model_info(
            "expired-key",
            status="replacement_grace",
            replacement_retire_at="2000-01-01T00:00:00+00:00",
        ),
        _model_info(
            "future-key",
            status="replacement_grace",
            replacement_retire_at="2100-01-01T00:00:00+00:00",
        ),
        {"model_info": {"id": "foreign-key", MANAGED_MARKER: False}},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET" and request.url.path == "/model/info":
            return httpx.Response(200, json={"data": records})
        if request.method == "GET" and request.url.path == "/health":
            assert request.url.params["model_id"] == "healthy-key"
            return httpx.Response(200, json={"healthy_endpoints": [{"model": "ok"}]})
        if request.method == "PATCH" and request.url.path.endswith("/update"):
            return httpx.Response(200, json={"status": "ok"})
        if request.method == "POST" and request.url.path == "/model/delete":
            return httpx.Response(200, json={"deleted": True})
        raise AssertionError(f"unexpected management route: {request.url}")

    admin, http_client = _admin_client(httpx.MockTransport(handler))
    try:
        assert await admin.test_key("healthy-key") is True
        await admin.mark_replacement_grace(
            "healthy-key", retire_at=datetime(2030, 1, 1, tzinfo=UTC)
        )
        deleted = await admin.cleanup_expired_replacements()
    finally:
        await http_client.aclose()

    assert deleted == 1
    patches = [
        (request.url.path, json.loads(request.content))
        for request in requests
        if request.method == "PATCH"
    ]
    assert patches[0][0] == "/model/healthy-key/update"
    health_update = patches[0][1]["model_info"]
    assert health_update["status"] == "healthy"
    assert health_update["failure_count"] == 0
    assert health_update["last_error"] is None
    assert isinstance(health_update["last_tested_at"], str)
    assert datetime.fromisoformat(health_update["last_tested_at"]).tzinfo is not None
    assert patches[1] == (
        "/model/healthy-key/update",
        {
            "model_info": {
                "status": "replacement_grace",
                "replacement_retire_at": "2030-01-01T00:00:00+00:00",
            }
        },
    )
    deletes = [
        json.loads(request.content)["id"]
        for request in requests
        if request.method == "POST" and request.url.path == "/model/delete"
    ]
    assert deletes == ["expired-key"]


@pytest.mark.asyncio
async def test_failed_admin_error_does_not_expose_upstream_body() -> None:
    secret = "sk-upstream-secret"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/model/info":
            return httpx.Response(
                200,
                json={"data": [_model_info("managed-key")]},
            )
        return httpx.Response(500, json={"detail": secret})

    admin, http_client = _admin_client(httpx.MockTransport(handler))
    try:
        with pytest.raises(LiteLLMAdminError) as raised:
            await admin.test_key("managed-key")
    finally:
        await http_client.aclose()

    assert str(raised.value) == "unavailable"
    assert secret not in str(raised.value)
    assert [request.url.path for request in requests] == ["/model/info", "/health"]
