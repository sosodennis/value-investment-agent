from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request

from api.server import handle_request_validation_error
from src.auth.entrypoint import (
    Principal,
    require_current_user,
    require_current_user_mutation,
)
from src.search_settings.composition.routes import search_settings_router
from src.search_settings.domain import (
    ProviderCapabilities,
    ProviderKeyResult,
    ProviderPreference,
    ProviderSetting,
    SearchSettingsSnapshot,
)
from src.search_settings.infrastructure.client import SearchServiceClient


class FakeSearchService:
    def __init__(self) -> None:
        self.principals: list[str] = []
        self.key: str | None = None

    async def read(
        self, *, principal: str
    ) -> tuple[list[ProviderCapabilities], SearchSettingsSnapshot]:
        self.principals.append(principal)
        return [
            ProviderCapabilities(
                provider="ddgs", operations=["web", "news"], key_required=False
            )
        ], SearchSettingsSnapshot(
            providers=[ProviderSetting(provider="ddgs", enabled=True, priority=0)]
        )

    async def update(
        self, *, principal: str, providers: list[ProviderPreference]
    ) -> SearchSettingsSnapshot:
        self.principals.append(principal)
        return SearchSettingsSnapshot(
            providers=[
                ProviderSetting(
                    provider=item.provider, enabled=item.enabled, priority=item.priority
                )
                for item in providers
            ]
        )

    async def add_key(
        self, *, principal: str, provider: str, api_key: str, label: str
    ) -> ProviderKeyResult:
        self.principals.append(principal)
        self.key = api_key
        return ProviderKeyResult(
            id="key-1",
            provider=provider,
            tested=True,
            active=True,
            suffix=api_key[-4:],
            fingerprint="fp-safe",
        )

    async def replace_key(
        self, *, principal: str, key_id: str, provider: str, api_key: str, label: str
    ) -> ProviderKeyResult:
        return await self.add_key(
            principal=principal, provider=provider, api_key=api_key, label=label
        )

    async def delete_key(self, *, principal: str, key_id: str) -> None:
        self.principals.append(principal)

    async def set_key_enabled(
        self, *, principal: str, key_id: str, enabled: bool
    ) -> ProviderKeyResult:
        self.principals.append(principal)
        return ProviderKeyResult(
            id=key_id,
            provider="provider-a",
            tested=True,
            active=enabled,
            suffix="cdef",
            fingerprint="fp-safe",
        )


def make_app(service: FakeSearchService, principal_id: str) -> FastAPI:
    app = FastAPI()
    app.include_router(search_settings_router)
    principal = Principal(
        user_id=principal_id, subject=principal_id, email=f"{principal_id}@example.com"
    )
    app.dependency_overrides[require_current_user] = lambda: principal
    app.dependency_overrides[require_current_user_mutation] = lambda: principal
    from src.search_settings.composition.routes import get_search_service

    app.dependency_overrides[get_search_service] = lambda: service
    return app


@pytest.mark.asyncio
async def test_bff_uses_authenticated_principal_and_returns_only_masked_key_metadata() -> (
    None
):
    service = FakeSearchService()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=make_app(service, "user-a")),
        base_url="http://test",
    ) as client:
        settings = await client.get("/api/search/settings")
        created = await client.post(
            "/api/search/settings/keys",
            json={
                "provider": "provider-a",
                "api_key": "raw-secret-abcdef",
                "label": "Primary",
            },
        )
        disabled = await client.patch(
            "/api/search/settings/keys/key-1", json={"enabled": False}
        )
    assert settings.status_code == 200
    assert created.status_code == 201
    assert service.principals == ["user-a", "user-a", "user-a"]
    assert service.key == "raw-secret-abcdef"
    assert "raw-secret" not in json.dumps(created.json())
    assert created.json()["suffix"] == "cdef"
    assert disabled.status_code == 200
    assert disabled.json()["active"] is False


@pytest.mark.asyncio
async def test_caller_cannot_choose_another_users_settings_owner() -> None:
    service = FakeSearchService()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=make_app(service, "user-a")),
        base_url="http://test",
    ) as client:
        response = await client.put(
            "/api/search/settings",
            json={
                "user_id": "user-b",
                "providers": [{"provider": "ddgs", "enabled": False, "priority": 0}],
            },
        )
    assert response.status_code == 422
    assert service.principals == []


@pytest.mark.asyncio
async def test_search_transport_forwards_context_and_service_token_without_browser_cookies() -> (
    None
):
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "contract_version": "internal.v1",
                "correlation_id": "corr",
                "result": {
                    "id": "key-1",
                    "provider": "provider-a",
                    "tested": True,
                    "active": True,
                    "suffix": "w-key",
                    "fingerprint": "fp-safe",
                },
            },
        )

    transport = httpx.MockTransport(respond)
    client = httpx.AsyncClient(transport=transport)
    service = SearchServiceClient(
        base_url="http://search", token="service-secret", client=client
    )
    await service.add_key(
        principal="user-a", provider="provider-a", api_key="raw-key", label="Primary"
    )
    request = seen[0]
    body = json.loads(request.content)
    assert request.url.path == "/v1/provider-keys/add"
    assert request.headers["authorization"] == "Bearer service-secret"
    assert "cookie" not in request.headers
    assert body["context"]["principal"]["subject_id"] == "user-a"
    assert body["input"]["api_key"] == "raw-key"
    assert body["input"]["label"] == "Primary"
    await service.set_key_enabled(principal="user-a", key_id="key-1", enabled=False)
    assert seen[1].url.path == "/v1/provider-keys/set-enabled"
    assert json.loads(seen[1].content)["input"] == {
        "key_id": "key-1",
        "enabled": False,
    }
    await client.aclose()


@pytest.mark.asyncio
async def test_key_validation_errors_do_not_echo_submitted_key() -> None:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/search/settings/keys",
            "headers": [],
            "query_string": b"",
            "server": ("test", 80),
            "scheme": "http",
            "client": ("test", 1),
        }
    )
    error = RequestValidationError(
        [
            {
                "loc": ("body", "api_key"),
                "msg": "invalid key",
                "type": "value_error",
                "input": "raw-secret-key",
            }
        ]
    )
    response = await handle_request_validation_error(request, error)
    assert b"raw-secret-key" not in response.body
