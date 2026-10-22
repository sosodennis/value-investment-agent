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
from src.llm_provider.domain.errors import OpenRouterKeyTestError
from src.llm_provider.domain.key_metadata import key_fingerprint
from src.llm_provider.domain.provider_models import (
    ManagedProviderKey,
    OpenRouterModel,
    ProviderKeyHealth,
)
from src.llm_provider.domain.routes import user_route_alias


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
        release=AsyncMock(),
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
            "/api/llm/provider-keys",
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
    own_id = "57b2c97e-64c5-4a3f-9ef9-a4ae960dbfb5"
    other_id = "90970b8a-1011-4d24-9e13-aed6dc2b76f5"
    ownership = _ownership(owned_ids={own_id})
    telemetry = SimpleNamespace(
        get_many=AsyncMock(
            return_value={
                own_id: ProviderKeyHealth(
                    status="cooldown",
                    failure_count=2,
                    cooldown_until="2099-10-21T00:00:00+00:00",
                    last_error="rate_limited",
                    last_used_at="2026-10-21T00:00:00+00:00",
                ),
                other_id: ProviderKeyHealth(
                    status="healthy",
                    failure_count=0,
                    cooldown_until=None,
                    last_error=None,
                    last_used_at="2026-10-21T00:00:00+00:00",
                ),
            }
        ),
        delete=AsyncMock(),
    )
    managed = [
        ManagedProviderKey(own_id, "primary", "9abc", "fingerprint-a", None),
        ManagedProviderKey(other_id, "other user", "8def", "fingerprint-b", None),
    ]
    with (
        patch(
            "src.llm_provider.application.wiring.get_ownership_service",
            return_value=ownership,
        ),
        patch(
            "src.llm_provider.application.wiring.get_provider_key_telemetry",
            return_value=telemetry,
        ),
        patch(
            "src.llm_provider.infrastructure.litellm_admin.LiteLLMAdminClient.list_managed",
            new=AsyncMock(return_value=managed),
        ),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.get("/api/llm/provider-keys")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": own_id,
            "label": "primary",
            "suffix": "9abc",
            "fingerprint": "fingerprint-a",
            "created_at": None,
            "status": "cooldown",
            "last_tested_at": None,
            "failure_count": 2,
            "cooldown_until": "2099-10-21T00:00:00+00:00",
            "last_error": "rate_limited",
            "last_used_at": "2026-10-21T00:00:00+00:00",
            "replacement_retire_at": None,
        }
    ]
    assert other_id not in response.text
    telemetry.get_many.assert_awaited_once_with({own_id})
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
    managed = ManagedProviderKey(
        "managed-a", "primary", "9abc", "fingerprint-a", "2026-10-21T00:00:00+00:00"
    )
    with (
        patch(
            "src.llm_provider.application.wiring.get_ownership_service",
            return_value=ownership,
        ),
        patch(
            "src.llm_provider.application.wiring.test_openrouter_key", new=AsyncMock()
        ),
        patch(
            "src.llm_provider.infrastructure.litellm_admin.LiteLLMAdminClient.list_managed",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "src.llm_provider.infrastructure.litellm_admin.LiteLLMAdminClient.add_key",
            new=AsyncMock(return_value=managed),
        ) as add_key,
        patch(
            "src.llm_provider.application.wiring.get_selected_model",
            new=AsyncMock(return_value="openrouter/free"),
        ),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/api/llm/provider-keys",
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
    existing = ManagedProviderKey(
        "managed-a", "primary", "9abc", key_fingerprint(secret), None
    )
    ownership = _ownership(owned_ids={"managed-a"})
    with (
        patch(
            "src.llm_provider.application.wiring.get_ownership_service",
            return_value=ownership,
        ),
        patch(
            "src.llm_provider.application.wiring.test_openrouter_key", new=AsyncMock()
        ),
        patch(
            "src.llm_provider.infrastructure.litellm_admin.LiteLLMAdminClient.list_managed",
            new=AsyncMock(return_value=[existing]),
        ),
        patch(
            "src.llm_provider.infrastructure.litellm_admin.LiteLLMAdminClient.add_key",
            new=AsyncMock(),
        ) as add_key,
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/api/llm/provider-keys",
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
    existing = ManagedProviderKey(
        "managed-a", "user a", "9abc", key_fingerprint(secret), None
    )
    created = ManagedProviderKey(
        "managed-b", "user b", "9abc", key_fingerprint(secret), None
    )
    ownership = _ownership(owned_ids=set())
    with (
        patch(
            "src.llm_provider.application.wiring.get_ownership_service",
            return_value=ownership,
        ),
        patch(
            "src.llm_provider.application.wiring.test_openrouter_key", new=AsyncMock()
        ),
        patch(
            "src.llm_provider.infrastructure.litellm_admin.LiteLLMAdminClient.list_managed",
            new=AsyncMock(return_value=[existing]),
        ),
        patch(
            "src.llm_provider.infrastructure.litellm_admin.LiteLLMAdminClient.add_key",
            new=AsyncMock(return_value=created),
        ) as add_key,
        patch(
            "src.llm_provider.application.wiring.get_selected_model",
            new=AsyncMock(return_value="openrouter/free"),
        ),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/api/llm/provider-keys",
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
            "src.llm_provider.application.wiring.test_openrouter_key",
            new=AsyncMock(side_effect=OpenRouterKeyTestError("invalid_key")),
        ),
        patch(
            "src.llm_provider.infrastructure.litellm_admin.LiteLLMAdminClient.add_key",
            new=AsyncMock(),
        ) as add_key,
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/api/llm/provider-keys",
                json={"label": "primary", "api_key": "sk-or-v1-test-secret"},
            )
    assert response.status_code == 400
    add_key.assert_not_awaited()


@pytest.mark.asyncio
async def test_replace_key_tests_new_key_before_marking_old_key_for_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_GATEWAY_BASE_URL", "http://gateway")
    monkeypatch.setenv("LLM_GATEWAY_API_KEY", "gateway-admin")
    _as_user("user-a")
    ownership = _ownership(owned_ids={"managed-old"})
    old_key = ManagedProviderKey(
        "managed-old", "primary", "9abc", "old-fingerprint", None
    )
    replacement = ManagedProviderKey(
        "managed-new", "primary replacement", "8def", "new-fingerprint", None
    )
    with (
        patch(
            "src.llm_provider.application.wiring.get_ownership_service",
            return_value=ownership,
        ),
        patch(
            "src.llm_provider.application.wiring.test_openrouter_key", new=AsyncMock()
        ) as probe,
        patch(
            "src.llm_provider.infrastructure.litellm_admin.LiteLLMAdminClient.list_managed",
            new=AsyncMock(return_value=[old_key]),
        ),
        patch(
            "src.llm_provider.infrastructure.litellm_admin.LiteLLMAdminClient.add_key",
            new=AsyncMock(return_value=replacement),
        ) as add_key,
        patch(
            "src.llm_provider.infrastructure.litellm_admin.LiteLLMAdminClient.mark_replacement_grace",
            new=AsyncMock(),
        ) as mark_grace,
        patch(
            "src.llm_provider.infrastructure.litellm_admin.LiteLLMAdminClient.delete_key",
            new=AsyncMock(),
        ) as delete_key,
        patch(
            "src.llm_provider.application.wiring.get_selected_model",
            new=AsyncMock(return_value="openrouter/free"),
        ),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/api/llm/provider-keys/managed-old/replace",
                json={
                    "label": "primary replacement",
                    "api_key": "sk-or-v1-new-valid-key",
                },
            )

    assert response.status_code == 201
    assert response.json()["id"] == "managed-new"
    probe.assert_awaited_once_with("sk-or-v1-new-valid-key")
    assert add_key.await_args.kwargs["existing_ids"] == {"managed-old"}
    ownership.claim.assert_awaited_once_with(
        user_id="user-a",
        resource_type="provider_key",
        resource_id="managed-new",
    )
    mark_grace.assert_awaited_once()
    assert mark_grace.await_args.args == ("managed-old",)
    delete_key.assert_not_awaited()


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
            "/api/llm/provider-keys",
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
        patch(
            "src.llm_provider.application.wiring.get_ownership_service",
            return_value=ownership,
        ),
        patch(
            "src.llm_provider.infrastructure.litellm_admin.LiteLLMAdminClient.test_key",
            new=test_key,
        ),
        patch(
            "src.llm_provider.infrastructure.litellm_admin.LiteLLMAdminClient.delete_key",
            new=delete_key,
        ),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            test_response = await client.post("/api/llm/provider-keys/managed-b/test")
            delete_response = await client.delete("/api/llm/provider-keys/managed-b")

    assert test_response.status_code == 404
    assert delete_response.status_code == 404
    test_key.assert_not_awaited()
    delete_key.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_key_releases_ownership_after_gateway_deletion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_GATEWAY_BASE_URL", "http://gateway")
    monkeypatch.setenv("LLM_GATEWAY_API_KEY", "gateway-admin")
    _as_user("user-a")
    ownership = _ownership(owns=True)
    with (
        patch(
            "src.llm_provider.application.wiring.get_ownership_service",
            return_value=ownership,
        ),
        patch(
            "src.llm_provider.infrastructure.litellm_admin.LiteLLMAdminClient.delete_key",
            new=AsyncMock(),
        ) as delete_key,
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.delete("/api/llm/provider-keys/managed-a")

    assert response.status_code == 204
    delete_key.assert_awaited_once_with("managed-a")
    ownership.release.assert_awaited_once_with(
        resource_type="provider_key", resource_id="managed-a"
    )


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
        patch(
            "src.llm_provider.application.wiring.list_free_models",
            new=AsyncMock(return_value=models),
        ),
        patch(
            "src.llm_provider.application.wiring.get_selected_model",
            new=AsyncMock(return_value="openrouter/free"),
        ),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.get("/api/llm/settings")
    assert response.status_code == 200
    assert response.json()["selected_model"] == "openrouter/free"
    assert response.json()["models"][0]["id"] == "openrouter/free"


@pytest.mark.parametrize("selected_model", ["openrouter/free", "anthropic/model:free"])
@pytest.mark.asyncio
async def test_llm_settings_update_requires_free_model_and_authenticated_mutation(
    monkeypatch: pytest.MonkeyPatch, selected_model: str
) -> None:
    _as_user("user-a")
    models = (
        OpenRouterModel(
            id="openrouter/free",
            name="Free Models Router",
            description=None,
            context_length=None,
        ),
        OpenRouterModel(
            id="anthropic/model:free",
            name="Example Free Model",
            description=None,
            context_length=None,
        ),
    )
    with (
        patch(
            "src.llm_provider.application.wiring.validate_free_model",
            new=AsyncMock(return_value=False),
        ) as validate_model,
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.put(
                "/api/llm/settings",
                json={"selected_model": "openai/gpt-4o"},
            )
    assert response.status_code == 400
    validate_model.assert_awaited_once_with("openai/gpt-4o")

    monkeypatch.setenv("LLM_GATEWAY_BASE_URL", "http://gateway")
    monkeypatch.setenv("LLM_GATEWAY_API_KEY", "gateway-admin")
    with (
        patch(
            "src.llm_provider.application.wiring.list_free_models",
            new=AsyncMock(return_value=models),
        ),
        patch(
            "src.llm_provider.application.wiring.validate_free_model",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "src.llm_provider.application.wiring.get_selected_model",
            new=AsyncMock(return_value=selected_model),
        ),
        patch(
            "src.llm_provider.application.wiring.set_selected_model",
            new=AsyncMock(),
        ) as set_model,
        patch(
            "src.llm_provider.infrastructure.litellm_admin.LiteLLMAdminClient.update_model",
            new=AsyncMock(),
        ) as update_model,
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.put(
                "/api/llm/settings",
                json={"selected_model": selected_model},
            )
    assert response.status_code == 200
    assert response.json()["selected_model"] == selected_model
    set_model.assert_awaited_once_with(selected_model, updated_by="user-a")
    update_model.assert_awaited_once_with(selected_model)
