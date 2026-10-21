from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import ValidationError

from api.server import RequestSchema, app
from src.infrastructure.llm.litellm_admin import ManagedKey
from src.infrastructure.llm.openrouter_key_test import OpenRouterKeyTestError
from src.infrastructure.llm.openrouter_models import OpenRouterModel


@pytest.mark.asyncio
async def test_llm_key_routes_require_admin_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("LLM_PROVIDER_ADMIN_TOKEN", raising=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/settings/openrouter-keys")
    assert response.status_code == 503


def test_stream_request_rejects_model_override() -> None:
    with pytest.raises(ValidationError):
        RequestSchema(thread_id="thread-1", message="hello", model="openrouter/free")


@pytest.mark.asyncio
async def test_local_admin_session_authorizes_key_routes_on_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("LLM_GATEWAY_BASE_URL", "http://gateway")
    monkeypatch.setenv("LLM_GATEWAY_API_KEY", "gateway-admin")
    with patch(
        "api.server.LiteLLMAdminClient.list_managed",
        new=AsyncMock(return_value=[]),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:3001"
        ) as client:
            session = await client.post(
                "/api/auth/local-admin/session",
                headers={"Origin": "http://127.0.0.1:3001"},
            )
            response = await client.get(
                "/api/settings/openrouter-keys",
                headers={"Origin": "http://127.0.0.1:3001"},
            )
    assert session.status_code == 200
    assert session.json() == {
        "subject": "local-admin",
        "role": "platform_admin",
        "auth_type": "local",
    }
    assert "local_admin_session=" in session.headers["set-cookie"]
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_local_admin_session_rejects_non_loopback_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://example.test"
    ) as client:
        response = await client.post(
            "/api/auth/local-admin/session",
            headers={"Origin": "http://127.0.0.1:3001"},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_llm_key_routes_reject_wrong_admin_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LLM_PROVIDER_ADMIN_TOKEN", "admin")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            "/api/settings/openrouter-keys",
            headers={"Authorization": "Bearer wrong"},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_llm_keys_returns_masked_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LLM_PROVIDER_ADMIN_TOKEN", "admin")
    monkeypatch.setenv("LLM_GATEWAY_BASE_URL", "http://gateway")
    monkeypatch.setenv("LLM_GATEWAY_API_KEY", "gateway-admin")
    with patch(
        "api.server.LiteLLMAdminClient.list_managed",
        new=AsyncMock(
            return_value=[
                ManagedKey(
                    id="managed-id",
                    label="primary",
                    suffix="9abc",
                    fingerprint="f00dbabe",
                    created_at="2026-10-21T00:00:00+00:00",
                )
            ]
        ),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.get(
                "/api/settings/openrouter-keys",
                headers={"Authorization": "Bearer admin"},
            )
    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "managed-id",
            "label": "primary",
            "suffix": "9abc",
            "fingerprint": "f00dbabe",
            "created_at": "2026-10-21T00:00:00+00:00",
        }
    ]
    assert "api_key" not in response.text


@pytest.mark.asyncio
async def test_add_key_does_not_register_when_openrouter_probe_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LLM_PROVIDER_ADMIN_TOKEN", "admin")
    monkeypatch.setenv("LLM_GATEWAY_BASE_URL", "http://gateway")
    monkeypatch.setenv("LLM_GATEWAY_API_KEY", "gateway-admin")
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
                headers={"Authorization": "Bearer admin"},
                json={"label": "primary", "api_key": "sk-or-v1-test-secret"},
            )
    assert response.status_code == 400
    add_key.assert_not_awaited()


@pytest.mark.asyncio
async def test_validation_error_does_not_echo_submitted_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LLM_PROVIDER_ADMIN_TOKEN", "admin")
    monkeypatch.setenv("LLM_GATEWAY_BASE_URL", "http://gateway")
    monkeypatch.setenv("LLM_GATEWAY_API_KEY", "gateway-admin")
    secret = "short-api-secret"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/settings/openrouter-keys",
            headers={"Authorization": "Bearer admin"},
            json={"label": "primary", "api_key": secret},
        )
    assert response.status_code == 422
    assert secret not in response.text


@pytest.mark.asyncio
async def test_llm_settings_lists_free_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LLM_PROVIDER_ADMIN_TOKEN", "admin")
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
            response = await client.get(
                "/api/settings/llm", headers={"Authorization": "Bearer admin"}
            )
    assert response.status_code == 200
    assert response.json()["selected_model"] == "openrouter/free"
    assert response.json()["models"][0]["id"] == "openrouter/free"


@pytest.mark.asyncio
async def test_llm_settings_rejects_paid_or_unknown_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LLM_PROVIDER_ADMIN_TOKEN", "admin")
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
                headers={"Authorization": "Bearer admin"},
                json={"selected_model": "openai/gpt-4o"},
            )
    assert response.status_code == 400
