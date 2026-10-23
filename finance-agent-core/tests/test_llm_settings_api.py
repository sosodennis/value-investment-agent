from __future__ import annotations

import httpx
import pytest

from api.server import app
from src.auth.interface.contracts import Principal
from src.auth.interface.dependencies import (
    require_current_user,
    require_current_user_mutation,
)
from src.llm_provider.application.wiring import get_provider_settings_service
from src.llm_provider.domain.errors import ProviderSettingsError
from src.llm_provider.domain.provider_models import ManagedProviderKey, OpenRouterModel


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


class _Service:
    def __init__(self) -> None:
        self.key = ManagedProviderKey(
            "managed-a", "primary", "9abc", "fingerprint-a", None
        )
        self.models = (
            OpenRouterModel("openrouter/free", "Free Models Router", "router", None),
        )
        self.calls: list[tuple[str, object]] = []

    async def list_keys(self, *, user_id: str):
        self.calls.append(("list_keys", user_id))
        return [self.key]

    async def add_key(self, *, user_id: str, key: str, label: str):
        self.calls.append(("add_key", (user_id, key, label)))
        return self.key

    async def test_key(self, *, user_id: str, key_id: str):
        self.calls.append(("test_key", (user_id, key_id)))
        return True

    async def delete_key(self, *, user_id: str, key_id: str):
        self.calls.append(("delete_key", (user_id, key_id)))

    async def selected_model_settings(self, *, user_id: str):
        _ = user_id
        self.calls.append(("selected_model_settings", None))
        return "openrouter/free", self.models

    async def update_selected_model(self, *, model_id: str, user_id: str):
        self.calls.append(("update_selected_model", (model_id, user_id)))
        if model_id != "openrouter/free":
            raise ProviderSettingsError("model_not_free")
        return model_id


def _client(service: _Service) -> httpx.AsyncClient:
    principal = Principal(
        user_id="user-a", subject="user-a", email="user-a@example.test"
    )
    app.dependency_overrides[require_current_user] = lambda: principal
    app.dependency_overrides[require_current_user_mutation] = lambda: principal
    app.dependency_overrides[get_provider_settings_service] = lambda: service
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
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


@pytest.mark.asyncio
async def test_provider_key_routes_delegate_to_provider_service() -> None:
    service = _Service()
    async with _client(service) as client:
        listed = await client.get("/api/llm/provider-keys")
        created = await client.post(
            "/api/llm/provider-keys",
            json={"api_key": "sk-this-is-a-long-test-secret", "label": "primary"},
        )
        tested = await client.post("/api/llm/provider-keys/managed-a/test")
        deleted = await client.delete("/api/llm/provider-keys/managed-a")
    assert listed.status_code == 200
    assert created.status_code == 201
    assert "sk-this-is-a-long-test-secret" not in created.text
    assert tested.status_code == 200
    assert deleted.status_code == 204
    assert [call[0] for call in service.calls] == [
        "list_keys",
        "add_key",
        "test_key",
        "delete_key",
    ]


@pytest.mark.asyncio
async def test_settings_routes_delegate_and_map_validation_errors() -> None:
    service = _Service()
    async with _client(service) as client:
        read = await client.get("/api/llm/settings")
        updated = await client.put(
            "/api/llm/settings", json={"selected_model": "openrouter/free"}
        )
        rejected = await client.put(
            "/api/llm/settings", json={"selected_model": "paid/model"}
        )
    assert read.status_code == 200
    assert updated.status_code == 200
    assert rejected.status_code == 400
    assert rejected.json()["detail"] == "model_not_free"
