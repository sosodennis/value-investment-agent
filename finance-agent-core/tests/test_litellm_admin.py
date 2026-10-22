from __future__ import annotations

import json

import httpx
import pytest

from src.infrastructure.llm.litellm_admin import (
    MANAGED_MARKER,
    LiteLLMAdminClient,
    LiteLLMAdminError,
    key_fingerprint,
    key_suffix,
)


@pytest.mark.asyncio
async def test_list_filters_unmanaged_models_and_redacts_key() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer admin"
        assert request.method == "GET"
        assert request.url.path == "/model/info"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "model_info": {
                            "id": "managed-id",
                            MANAGED_MARKER: True,
                            "label": "primary",
                            "suffix": "9abc",
                            "fingerprint": "f00dbabe",
                        },
                        "litellm_params": {"api_key": "sk-secret"},
                    },
                    {"model_info": {"id": "other-id"}},
                ]
            },
        )

    client = LiteLLMAdminClient(
        base_url="http://gateway/v1",
        admin_token="admin",
        openrouter_headers={"X-Title": "Tests"},
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    keys = await client.list_managed()
    await client.close()
    assert len(keys) == 1
    assert keys[0].id == "managed-id"
    assert "secret" not in repr(keys[0])


@pytest.mark.parametrize(
    ("model", "litellm_model"),
    [
        ("openrouter/free", "openrouter/openrouter/free"),
        ("anthropic/model:free", "openrouter/anthropic/model:free"),
    ],
)
@pytest.mark.asyncio
async def test_add_key_sends_secret_only_to_gateway(
    model: str, litellm_model: str
) -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert request.url.path == "/model/info"
            return httpx.Response(200, json={"data": []})
        assert request.url.path == "/model/new"
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"model_id": "created-id"})

    client = LiteLLMAdminClient(
        base_url="http://gateway/v1",
        admin_token="admin",
        openrouter_headers={"X-Title": "Tests"},
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    managed = await client.add_key(key="sk-or-v1-secret", label="test", model=model)
    await client.close()
    assert managed.id == "created-id"
    assert captured["model_name"] == "openrouter-default"
    assert captured["litellm_params"]["api_key"] == "sk-or-v1-secret"
    assert captured["litellm_params"]["model"] == litellm_model
    assert captured["litellm_params"]["headers"] == {"X-Title": "Tests"}
    assert managed.suffix == key_suffix("sk-or-v1-secret")
    assert managed.fingerprint == key_fingerprint("sk-or-v1-secret")


@pytest.mark.asyncio
async def test_add_key_fails_if_gateway_does_not_confirm_registration() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert request.url.path == "/model/info"
            return httpx.Response(200, json={"data": []})
        assert request.url.path == "/model/new"
        return httpx.Response(200, json={"ok": True})

    client = LiteLLMAdminClient(
        base_url="http://gateway/v1",
        admin_token="admin",
        openrouter_headers={"X-Title": "Tests"},
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(LiteLLMAdminError, match="did not confirm key registration"):
        await client.add_key(
            key="sk-or-v1-secret", label="test", model="openrouter/free"
        )
    await client.close()


@pytest.mark.asyncio
async def test_test_key_rejects_an_unhealthy_model() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/model/info"):
            assert request.url.path == "/model/info"
            return httpx.Response(
                200,
                json={
                    "data": [{"model_info": {"id": "managed-id", MANAGED_MARKER: True}}]
                },
            )
        assert request.url.path == "/health"
        return httpx.Response(
            200,
            json={
                "healthy_endpoints": [],
                "unhealthy_endpoints": [{"model": "openrouter/auto"}],
            },
        )

    client = LiteLLMAdminClient(
        base_url="http://gateway/v1",
        admin_token="admin",
        openrouter_headers={"X-Title": "Tests"},
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(LiteLLMAdminError, match="invalid_key"):
        await client.test_key("managed-id")
    await client.close()


@pytest.mark.asyncio
async def test_delete_rejects_unmanaged_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    client = LiteLLMAdminClient(
        base_url="http://gateway/v1",
        admin_token="admin",
        openrouter_headers={"X-Title": "Tests"},
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(LiteLLMAdminError, match="not found"):
        await client.delete_key("other-id")
    await client.close()


@pytest.mark.asyncio
async def test_delete_uses_gateway_management_root() -> None:
    requests: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path == "/model/info":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "model_info": {
                                "id": "managed-id",
                                MANAGED_MARKER: True,
                            }
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"deleted": True})

    client = LiteLLMAdminClient(
        base_url="http://gateway/v1",
        admin_token="admin",
        openrouter_headers={},
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await client.delete_key("managed-id")
    await client.close()

    assert requests == [
        ("GET", "/model/info"),
        ("POST", "/model/delete"),
    ]


@pytest.mark.asyncio
async def test_gateway_route_404_is_not_reported_as_missing_managed_key() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Not Found"})

    client = LiteLLMAdminClient(
        base_url="http://gateway/v1",
        admin_token="admin",
        openrouter_headers={},
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(
        LiteLLMAdminError, match="gateway management endpoint was not found"
    ):
        await client.list_managed()
    await client.close()


@pytest.mark.parametrize(
    ("model", "litellm_model"),
    [
        ("openrouter/free", "openrouter/openrouter/free"),
        ("anthropic/model:free", "openrouter/anthropic/model:free"),
    ],
)
@pytest.mark.asyncio
async def test_update_model_updates_only_project_managed_deployments(
    model: str, litellm_model: str
) -> None:
    requests: list[tuple[str, str, dict[str, object] | None]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        requests.append((request.method, request.url.path, body))
        if request.url.path == "/model/info":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"model_info": {"id": "managed-id", MANAGED_MARKER: True}},
                        {"model_info": {"id": "unmanaged-id"}},
                    ]
                },
            )
        return httpx.Response(200, json={"updated": True})

    client = LiteLLMAdminClient(
        base_url="http://gateway",
        admin_token="admin",
        openrouter_headers={},
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await client.update_model(model)
    await client.close()

    assert requests == [
        ("GET", "/model/info", None),
        (
            "PATCH",
            "/model/managed-id/update",
            {"litellm_params": {"model": litellm_model}},
        ),
    ]
