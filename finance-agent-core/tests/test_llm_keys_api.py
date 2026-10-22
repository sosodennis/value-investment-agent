from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import ValidationError

from api.server import RequestSchema, app
from src.auth.interface.contracts import Principal
from src.auth.interface.dependencies import (
    require_current_user,
    require_current_user_mutation,
)
from src.infrastructure.llm.litellm_admin import ManagedKey, key_fingerprint
from src.infrastructure.llm.openrouter_key_test import OpenRouterKeyTestError
from src.infrastructure.llm.openrouter_models import OpenRouterModel
from src.shared.llm.routes import user_route_alias


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def _principal(user_id: str) -> Principal:
    return Principal(
        user_id=user_id,
        subject=user_id,
        email=f"{user_id}@example.test",
    )


def _as_user(user_id: str) -> None:
    principal = _principal(user_id)
    app.dependency_overrides[require_current_user] = lambda: principal
    app.dependency_overrides[require_current_user_mutation] = lambda: principal


def _ownership(
    *,
    owned_ids: set[str] | None = None,
    owns: bool = True,
    claim: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        owned_ids=AsyncMock(return_value=owned_ids or set()),
        owns=AsyncMock(return_value=owns),
        claim=AsyncMock(return_value=claim),
    )


@pytest.mark.asyncio
async def test_provider_settings_require_authenticated_user_even_with_admin_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER_ADMIN_TOKEN", "legacy-admin-token")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            "/api/settings/openrouter-keys",
            headers={"Authorization": "Bearer legacy-admin-token"},
        )
    assert response.status_code == 401


def test_stream_request_rejects_model_override() -> None:
    with pytest.raises(ValidationError):
        RequestSchema(thread_id="thread-1", message="hello", model="openrouter/free")


@pytest.mark.asyncio
async def test_list_llm_keys_returns_only_current_users_owned_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_GATEWAY_BASE_URL", "http://gateway")
    monkeypatch.setenv("LLM_GATEWAY_API_KEY", "gateway-admin")
    _as_user("user-a")
    ownership = _ownership(owned_ids={"managed-a"})
    managed = [
        ManagedKey("managed-a", "primary", "9abc", "fingerprint-a", None),
        ManagedKey("managed-b", "other user", "8def", "fingerprint-b", None),
    ]
    with (
        patch("api.server.get_ownership_service", return_value=ownership),
        patch(
            "api.server.LiteLLMAdminClient.list_managed",
            new=AsyncMock(return_value=managed),
        ),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.get("/api/settings/openrouter-keys")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "managed-a",
            "label": "primary",
            "suffix": "9abc",
            "fingerprint": "fingerprint-a",
            "created_at": None,
        }
    ]
    assert "managed-b" not in response.text
    ownership.owned_ids.assert_awaited_once_with(
        user_id="user-a", resource_type="provider_key"
    )


@pytest.mark.asyncio
async def test_add_key_registers_in_current_users_gateway_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_GATEWAY_BASE_URL", "http://gateway")
    monkeypatch.setenv("LLM_GATEWAY_API_KEY", "gateway-admin")
    _as_user("user-a")
    ownership = _ownership()
    managed = ManagedKey(
        "managed-a", "primary", "9abc", "fingerprint-a", "2026-10-21T00:00:00+00:00"
    )
    with (
        patch("api.server.get_ownership_service", return_value=ownership),
        patch("api.server.test_openrouter_key", new=AsyncMock()),
        patch(
            "api.server.LiteLLMAdminClient.list_managed",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "api.server.LiteLLMAdminClient.add_key",
            new=AsyncMock(return_value=managed),
        ) as add_key,
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/api/settings/openrouter-keys",
                json={"label": "primary", "api_key": "sk-or-v1-test-openrouter-secret"},
            )

    assert response.status_code == 201
    assert response.json()["id"] == "managed-a"
    assert add_key.await_args.kwargs["model_name"] == user_route_alias("user-a")
    ownership.claim.assert_awaited_once_with(
        user_id="user-a", resource_type="provider_key", resource_id="managed-a"
    )


@pytest.mark.asyncio
async def test_duplicate_key_is_idempotent_only_for_current_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_GATEWAY_BASE_URL", "http://gateway")
    monkeypatch.setenv("LLM_GATEWAY_API_KEY", "gateway-admin")
    _as_user("user-a")
    secret = "sk-or-v1-test-openrouter-secret"
    existing = ManagedKey("managed-a", "primary", "9abc", key_fingerprint(secret), None)
    ownership = _ownership(owned_ids={"managed-a"})
    with (
        patch("api.server.get_ownership_service", return_value=ownership),
        patch("api.server.test_openrouter_key", new=AsyncMock()),
        patch(
            "api.server.LiteLLMAdminClient.list_managed",
            new=AsyncMock(return_value=[existing]),
        ),
        patch("api.server.LiteLLMAdminClient.add_key", new=AsyncMock()) as add_key,
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/api/settings/openrouter-keys",
                json={"label": "renamed", "api_key": secret},
            )

    assert response.status_code == 201
    assert response.json()["id"] == "managed-a"
    add_key.assert_not_awaited()
    ownership.claim.assert_not_awaited()


@pytest.mark.asyncio
async def test_same_key_owned_by_another_user_is_registered_without_deleting_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_GATEWAY_BASE_URL", "http://gateway")
    monkeypatch.setenv("LLM_GATEWAY_API_KEY", "gateway-admin")
    _as_user("user-b")
    secret = "sk-or-v1-test-openrouter-secret"
    existing = ManagedKey("managed-a", "user a", "9abc", key_fingerprint(secret), None)
    created = ManagedKey("managed-b", "user b", "9abc", key_fingerprint(secret), None)
    ownership = _ownership(owned_ids=set())
    with (
        patch("api.server.get_ownership_service", return_value=ownership),
        patch("api.server.test_openrouter_key", new=AsyncMock()),
        patch(
            "api.server.LiteLLMAdminClient.list_managed",
            new=AsyncMock(return_value=[existing]),
        ),
        patch(
            "api.server.LiteLLMAdminClient.add_key",
            new=AsyncMock(return_value=created),
        ) as add_key,
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/api/settings/openrouter-keys",
                json={"label": "user b", "api_key": secret},
            )

    assert response.status_code == 201
    assert response.json()["id"] == "managed-b"
    assert add_key.await_args.kwargs["existing_ids"] == set()
    ownership.claim.assert_awaited_once_with(
        user_id="user-b", resource_type="provider_key", resource_id="managed-b"
    )


@pytest.mark.asyncio
async def test_add_key_does_not_register_when_openrouter_probe_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_GATEWAY_BASE_URL", "http://gateway")
    monkeypatch.setenv("LLM_GATEWAY_API_KEY", "gateway-admin")
    _as_user("user-a")
    with (
        patch(
            "api.server.test_openrouter_key",
            new=AsyncMock(side_effect=OpenRouterKeyTestError("invalid_key")),
        ),
        patch("api.server.LiteLLMAdminClient.add_key", new=AsyncMock()) as add_key,
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/api/settings/openrouter-keys",
                json={"label": "primary", "api_key": "sk-or-v1-test-secret"},
            )
    assert response.status_code == 400
    add_key.assert_not_awaited()


@pytest.mark.asyncio
async def test_validation_error_does_not_echo_submitted_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_GATEWAY_BASE_URL", "http://gateway")
    monkeypatch.setenv("LLM_GATEWAY_API_KEY", "gateway-admin")
    _as_user("user-a")
    secret = "short-api-secret"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/settings/openrouter-keys",
            json={"label": "primary", "api_key": secret},
        )
    assert response.status_code == 422
    assert secret not in response.text


@pytest.mark.asyncio
async def test_test_and_delete_reject_key_owned_by_another_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_GATEWAY_BASE_URL", "http://gateway")
    monkeypatch.setenv("LLM_GATEWAY_API_KEY", "gateway-admin")
    _as_user("user-a")
    ownership = _ownership(owns=False)
    test_key = AsyncMock()
    delete_key = AsyncMock()
    with (
        patch("api.server.get_ownership_service", return_value=ownership),
        patch("api.server.LiteLLMAdminClient.test_key", new=test_key),
        patch("api.server.LiteLLMAdminClient.delete_key", new=delete_key),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            test_response = await client.post(
                "/api/settings/openrouter-keys/managed-b/test"
            )
            delete_response = await client.delete(
                "/api/settings/openrouter-keys/managed-b"
            )

    assert test_response.status_code == 404
    assert delete_response.status_code == 404
    test_key.assert_not_awaited()
    delete_key.assert_not_awaited()


@pytest.mark.asyncio
async def test_llm_settings_lists_free_models_for_authenticated_user() -> None:
    _as_user("user-a")
    models = (
        OpenRouterModel(
            id="openrouter/free",
            name="Free Models Router",
            description="router",
            context_length=None,
        ),
    )
    with (
        patch("api.server.list_free_models", new=AsyncMock(return_value=models)),
        patch(
            "api.server.get_selected_model",
            new=AsyncMock(return_value="openrouter/free"),
        ),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.get("/api/settings/llm")
    assert response.status_code == 200
    assert response.json()["selected_model"] == "openrouter/free"
    assert response.json()["models"][0]["id"] == "openrouter/free"


@pytest.mark.asyncio
async def test_llm_settings_update_requires_free_model_and_authenticated_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _as_user("user-a")
    models = (
        OpenRouterModel(
            id="openrouter/free",
            name="Free Models Router",
            description=None,
            context_length=None,
        ),
    )
    with patch("api.server.list_free_models", new=AsyncMock(return_value=models)):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.put(
                "/api/settings/llm",
                json={"selected_model": "openai/gpt-4o"},
            )
    assert response.status_code == 400

    monkeypatch.setenv("LLM_GATEWAY_BASE_URL", "http://gateway")
    monkeypatch.setenv("LLM_GATEWAY_API_KEY", "gateway-admin")
    gateway = SimpleNamespace(update_model=AsyncMock(), close=AsyncMock())
    with (
        patch("api.server.list_free_models", new=AsyncMock(return_value=models)),
        patch("api.server.validate_free_model", new=AsyncMock(return_value=True)),
        patch("api.server.get_litellm_admin_client", return_value=gateway),
        patch("api.server.set_selected_model", new=AsyncMock()) as set_model,
        patch(
            "api.server._llm_settings_response",
            new=AsyncMock(
                return_value={
                    "selected_model": "openrouter/free",
                    "default_model": "openrouter/free",
                    "models": [],
                }
            ),
        ),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.put(
                "/api/settings/llm",
                json={"selected_model": "openrouter/free"},
            )
    assert response.status_code == 200
    set_model.assert_awaited_once_with("openrouter/free", updated_by="user-a")
    gateway.update_model.assert_awaited_once_with("openrouter/free")
    gateway.close.assert_awaited_once_with()
