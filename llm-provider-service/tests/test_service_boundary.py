from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from src.llm_provider_service import app as service
from src.llm_provider_service.application.context import get_provider_principal
from src.llm_provider_service.domain.contracts import (
    CompletionResult,
    StreamEvent,
    Usage,
)
from src.llm_provider_service.domain.routes import DEFAULT_MODEL_ALIAS


class _Gateway:
    def __init__(self) -> None:
        self.completion_calls = 0
        self.stream_calls = 0
        self.principals: list[str | None] = []

    async def acomplete(self, request):
        self.completion_calls += 1
        principal = get_provider_principal()
        self.principals.append(principal.user_id if principal else None)
        return CompletionResult(
            request_id=request.request_id,
            text="answer",
            model=request.route.alias,
            usage=Usage(total_tokens=2),
        )

    async def acomplete_structured(self, request):
        self.completion_calls += 1
        return request.response_schema.model_validate({"answer": "ok"})

    async def astream(self, request) -> AsyncIterator[StreamEvent]:
        self.stream_calls += 1
        yield StreamEvent(
            kind="started",
            request_id=request.request_id,
            sequence=0,
            model=DEFAULT_MODEL_ALIAS,
        )
        yield StreamEvent(
            kind="delta",
            request_id=request.request_id,
            sequence=1,
            model=DEFAULT_MODEL_ALIAS,
            text="partial",
        )
        raise RuntimeError("upstream failure including sk-do-not-leak")


class _Settings:
    def __init__(self) -> None:
        self.owners = {"key-a": "alice"}
        self.secrets: list[str] = []
        self.list_delay = 0.0
        self.settings_delay = 0.0

    async def list_keys(self, *, user_id: str):
        if self.list_delay:
            await asyncio.sleep(self.list_delay)
        return [
            SimpleNamespace(
                id=key_id,
                label="personal",
                suffix="1234",
                fingerprint="fingerprint",
                created_at=None,
                status="healthy",
                last_tested_at=None,
                failure_count=0,
                cooldown_until=None,
                last_error=None,
                last_used_at=None,
                replacement_retire_at=None,
            )
            for key_id, owner in self.owners.items()
            if owner == user_id
        ]

    async def add_key(self, *, user_id: str, key: str, label: str):
        self.secrets.append(key)
        return SimpleNamespace(
            id="new-key",
            label=label,
            suffix=key[-4:],
            fingerprint="safe-fingerprint",
            created_at=None,
            status="untested",
            last_tested_at=None,
            failure_count=0,
            cooldown_until=None,
            last_error=None,
            last_used_at=None,
            replacement_retire_at=None,
        )

    async def test_key(self, *, user_id: str, key_id: str) -> bool:
        if self.owners.get(key_id) != user_id:
            from src.llm_provider_service.domain.errors import ProviderSettingsError

            raise ProviderSettingsError("not_found")
        return True

    async def selected_model_settings(self):
        if self.settings_delay:
            await asyncio.sleep(self.settings_delay)
        return "openrouter/free", ()

    async def update_selected_model(self, *, model_id: str, user_id: str):
        _ = (model_id, user_id)
        if self.settings_delay:
            await asyncio.sleep(self.settings_delay)
        return model_id


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER_SERVICE_TOKEN", "service-secret")
    gateway = _Gateway()
    settings = _Settings()
    service.app.state.runtime = SimpleNamespace(
        ready=True, gateway=gateway, settings=settings
    )
    transport = httpx.ASGITransport(app=service.app)
    return (
        httpx.AsyncClient(transport=transport, base_url="http://provider.test"),
        gateway,
        settings,
    )


def _context(
    *, user_id: str = "alice", deadline: datetime | None = None
) -> dict[str, object]:
    return {
        "principal": {"subject_id": user_id},
        "correlation_id": "correlation-120",
        "contract_version": "internal.v1",
        "deadline_at": (deadline or datetime.now(UTC) + timedelta(seconds=10))
        .isoformat()
        .replace("+00:00", "Z"),
    }


def _completion_input(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "llm.v1",
        "messages": [{"role": "user", "content": "hello"}],
        "route": {"alias": DEFAULT_MODEL_ALIAS},
        "request_id": "request-120",
        "operation": "test",
        "request_class": "interactive",
        "temperature": 0.0,
        "timeout_seconds": 5.0,
    }
    payload.update(updates)
    return payload


@pytest.mark.asyncio
async def test_authentication_precedes_principal_parsing(client) -> None:
    http, gateway, _ = client
    try:
        response = await http.post(
            "/v1/completions",
            headers={"Authorization": "Bearer wrong"},
            json={"context": {"principal": {"subject_id": ""}}, "input": {}},
        )
    finally:
        await http.aclose()

    assert response.status_code == 401
    assert gateway.completion_calls == 0
    assert response.json()["error"]["code"] == "internal_auth_invalid"


@pytest.mark.asyncio
async def test_provider_service_does_not_expose_internal_lifecycle_operations(
    client,
) -> None:
    http, _, _ = client
    try:
        sync = await http.post(
            "/internal/synchronize-model",
            headers={"Authorization": "Bearer service-secret"},
        )
        cleanup = await http.post(
            "/internal/cleanup-replacements",
            headers={"Authorization": "Bearer service-secret"},
        )
    finally:
        await http.aclose()

    assert sync.status_code == 404
    assert cleanup.status_code == 404


@pytest.mark.asyncio
async def test_runtime_is_closed_when_startup_fails(monkeypatch) -> None:
    class _Runtime:
        ready = False
        closed = False

        async def start(self) -> None:
            raise RuntimeError("startup failed")

        async def close(self) -> None:
            self.closed = True

    runtime = _Runtime()
    monkeypatch.setattr(service, "ProviderRuntime", lambda: runtime)
    application = SimpleNamespace(state=SimpleNamespace())

    with pytest.raises(RuntimeError, match="startup failed"):
        async with service.lifespan(application):
            pass

    assert runtime.closed


@pytest.mark.asyncio
async def test_completion_echoes_context_and_binds_authenticated_user(client) -> None:
    http, gateway, _ = client
    try:
        response = await http.post(
            "/v1/completions",
            headers={"Authorization": "Bearer service-secret"},
            json={"context": _context(), "input": _completion_input()},
        )
    finally:
        await http.aclose()

    assert response.status_code == 200
    body = response.json()
    assert body["correlation_id"] == "correlation-120"
    assert body["contract_version"] == "internal.v1"
    assert body["schema_version"] == "llm.v1"
    assert gateway.principals == ["alice"]


@pytest.mark.asyncio
async def test_invalid_context_deadline_and_non_allowlisted_route_are_rejected(
    client,
) -> None:
    http, gateway, _ = client
    headers = {"Authorization": "Bearer service-secret"}
    try:
        invalid = await http.post(
            "/v1/completions",
            headers=headers,
            json={
                "context": {**_context(), "contract_version": "internal.v2"},
                "input": _completion_input(),
            },
        )
        expired = await http.post(
            "/v1/completions",
            headers=headers,
            json={
                "context": _context(deadline=datetime.now(UTC) - timedelta(seconds=1)),
                "input": _completion_input(),
            },
        )
        route = await http.post(
            "/v1/completions",
            headers=headers,
            json={
                "context": _context(),
                "input": _completion_input(route={"alias": "user-selected"}),
            },
        )
    finally:
        await http.aclose()

    assert invalid.status_code == 400
    assert expired.status_code == 504
    assert route.status_code == 400
    assert gateway.completion_calls == 0


@pytest.mark.asyncio
async def test_provider_key_list_and_test_are_scoped_to_authenticated_user(
    client,
) -> None:
    http, _, settings = client
    headers = {"Authorization": "Bearer service-secret"}
    try:
        other_list = await http.post(
            "/v1/provider-keys/list",
            headers=headers,
            json={"context": _context(user_id="bob"), "input": {}},
        )
        other_test = await http.post(
            "/v1/provider-keys/test",
            headers=headers,
            json={"context": _context(user_id="bob"), "input": {"key_id": "key-a"}},
        )
    finally:
        await http.aclose()

    assert other_list.status_code == 200
    assert other_list.json()["result"]["keys"] == []
    assert other_test.status_code == 404
    assert settings.owners["key-a"] == "alice"


@pytest.mark.asyncio
async def test_provider_key_list_honors_deadline_during_operation(client) -> None:
    http, _, settings = client
    settings.list_delay = 0.05
    try:
        response = await http.post(
            "/v1/provider-keys/list",
            headers={"Authorization": "Bearer service-secret"},
            json={
                "context": _context(
                    deadline=datetime.now(UTC) + timedelta(milliseconds=10)
                ),
                "input": {},
            },
        )
    finally:
        await http.aclose()

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "deadline_exceeded"


@pytest.mark.asyncio
async def test_settings_read_honors_deadline_during_operation(client) -> None:
    http, _, settings = client
    settings.settings_delay = 0.05
    try:
        response = await http.post(
            "/v1/settings/read",
            headers={"Authorization": "Bearer service-secret"},
            json={
                "context": _context(
                    deadline=datetime.now(UTC) + timedelta(milliseconds=10)
                ),
                "input": {},
            },
        )
    finally:
        await http.aclose()

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "deadline_exceeded"


@pytest.mark.asyncio
async def test_secret_key_material_never_appears_in_create_response(client) -> None:
    http, _, settings = client
    secret = "sk-this-is-a-long-test-secret-value"
    try:
        response = await http.post(
            "/v1/provider-keys/create",
            headers={"Authorization": "Bearer service-secret"},
            json={
                "context": _context(),
                "input": {"api_key": secret, "label": "personal"},
            },
        )
    finally:
        await http.aclose()

    assert response.status_code == 200
    assert secret not in response.text
    assert secret in settings.secrets
    assert "suffix" in response.json()["result"]["key"]


@pytest.mark.asyncio
async def test_stream_failure_has_monotonic_sequence_without_replay(client) -> None:
    http, gateway, _ = client
    try:
        response = await http.post(
            "/v1/completions/stream",
            headers={"Authorization": "Bearer service-secret"},
            json={"context": _context(), "input": _completion_input()},
        )
    finally:
        await http.aclose()

    assert response.status_code == 200
    events = [
        json.loads(line[6:])["event"]
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert [event["sequence"] for event in events] == [0, 1, 2]
    assert events[-1]["kind"] == "error"
    assert events[-1]["error_code"] == "stream_interrupted"
    assert gateway.stream_calls == 1
    assert "sk-do-not-leak" not in response.text
