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
    CompletionRequest,
    CompletionResult,
    LLMErrorCode,
    LLMProviderError,
    StreamEvent,
    Usage,
)
from src.llm_provider_service.domain.errors import ProviderSettingsError
from src.llm_provider_service.domain.routes import DEFAULT_MODEL_ALIAS
from src.shared.internal_services import InternalPrincipal, build_internal_context


class _Provider:
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
        self.replacement_error_code: str | None = None

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

    async def replace_key(self, *, user_id: str, key_id: str, key: str, label: str):
        _ = (user_id, key_id, key, label)
        if self.replacement_error_code is None:
            raise AssertionError("replacement error code must be configured")
        raise ProviderSettingsError(self.replacement_error_code)

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
    provider = _Provider()
    settings = _Settings()
    service.app.state.runtime = SimpleNamespace(
        ready=True, provider=provider, settings=settings
    )
    transport = httpx.ASGITransport(app=service.app)
    return (
        httpx.AsyncClient(transport=transport, base_url="http://provider.test"),
        provider,
        settings,
    )


def _context(
    *, user_id: str = "alice", deadline: datetime | None = None
) -> dict[str, object]:
    resolved_deadline = deadline or datetime.now(UTC) + timedelta(seconds=10)
    return build_internal_context(
        principal=InternalPrincipal(
            subject_id=user_id,
            organization_id="organization-120",
            membership_id="membership-120",
        ),
        correlation_id="correlation-120",
        deadline_at=resolved_deadline,
        audience="llm-provider-service",
        signing_key="service-secret",
        issued_at=resolved_deadline - timedelta(seconds=5),
    ).model_dump(mode="json")


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
    http, provider, _ = client
    try:
        response = await http.post(
            "/v1/completions",
            headers={"Authorization": "Bearer wrong"},
            json={"context": {"principal": {"subject_id": ""}}, "input": {}},
        )
    finally:
        await http.aclose()

    assert response.status_code == 401
    assert provider.completion_calls == 0
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
@pytest.mark.parametrize(
    ("error_code", "expected_status"),
    [
        ("replacement_must_differ", 400),
        ("replacement_in_progress", 409),
    ],
)
async def test_provider_key_replacement_errors_have_client_statuses(
    client,
    monkeypatch: pytest.MonkeyPatch,
    error_code: str,
    expected_status: int,
) -> None:
    http, _, settings = client
    settings.replacement_error_code = error_code
    frozen_now = datetime(2026, 1, 1, tzinfo=UTC)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 1, 1, tzinfo=tz)

    monkeypatch.setattr(service, "datetime", FrozenDateTime)
    try:
        response = await http.post(
            "/v1/provider-keys/replace",
            headers={"Authorization": "Bearer service-secret"},
            json={
                "context": _context(deadline=frozen_now + timedelta(seconds=10)),
                "input": {
                    "key_id": "key-a",
                    "api_key": "sk-replacement-key-that-is-long-enough",
                    "label": "primary",
                },
            },
        )
    finally:
        await http.aclose()

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == error_code


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
    http, provider, _ = client
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
    assert provider.principals == ["alice"]


@pytest.mark.asyncio
async def test_invalid_context_deadline_and_non_allowlisted_route_are_rejected(
    client,
) -> None:
    http, provider, _ = client
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
    assert provider.completion_calls == 0


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
async def test_ordinary_key_create_action_is_removed(client) -> None:
    http, _, _ = client
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

    assert response.status_code == 404
    assert secret not in response.text


@pytest.mark.asyncio
async def test_stream_failure_has_monotonic_sequence_without_replay(client) -> None:
    http, provider, _ = client
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
    assert provider.stream_calls == 1
    assert "sk-do-not-leak" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize("request_timeout", [0.02, 5.0])
async def test_stream_deadline_emits_deadline_error_and_closes_upstream(
    client: tuple[httpx.AsyncClient, _Provider, _Settings],
    monkeypatch: pytest.MonkeyPatch,
    partial: bool,
    request_timeout: float,
) -> None:
    http, provider, _ = client
    closed = asyncio.Event()

    async def stalled(request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        try:
            if partial:
                yield StreamEvent(
                    kind="delta",
                    request_id=request.request_id,
                    sequence=0,
                    model=DEFAULT_MODEL_ALIAS,
                    text="partial",
                )
            await asyncio.Event().wait()
        finally:
            closed.set()

    monkeypatch.setattr(provider, "astream", stalled)
    async with http:
        response = await http.post(
            "/v1/completions/stream",
            headers={"Authorization": "Bearer service-secret"},
            json={
                "context": _context(
                    deadline=datetime.now(UTC) + timedelta(milliseconds=100)
                ),
                "input": _completion_input(timeout_seconds=request_timeout),
            },
        )

    frames = [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    events = [frame["event"] for frame in frames]
    assert response.status_code == 200
    assert [event["sequence"] for event in events] == list(range(2 if partial else 1))
    assert events[-1]["kind"] == "error"
    assert events[-1]["error_code"] == "deadline_exceeded"
    assert events[-1]["error_reason"] == "request deadline expired"
    assert all(frame["correlation_id"] == "correlation-120" for frame in frames)
    assert closed.is_set()


@pytest.mark.asyncio
async def test_stream_preserves_provider_error_before_output(
    client: tuple[httpx.AsyncClient, _Provider, _Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http, provider, _ = client

    async def rejected(request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        yield StreamEvent(
            kind="started",
            request_id=request.request_id,
            sequence=0,
            model=DEFAULT_MODEL_ALIAS,
        )
        raise LLMProviderError(
            code=LLMErrorCode.RATE_LIMITED,
            provider="test",
            model=request.route.alias,
            request_id=request.request_id,
            reason="sk-do-not-leak",
            retryable=False,
        )

    monkeypatch.setattr(provider, "astream", rejected)
    async with http:
        response = await http.post(
            "/v1/completions/stream",
            headers={"Authorization": "Bearer service-secret"},
            json={"context": _context(), "input": _completion_input()},
        )

    events = [
        json.loads(line[6:])["event"]
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    event = events[-1]
    assert event["error_code"] == "rate_limited"
    assert event["sequence"] == 1
    assert "sk-do-not-leak" not in response.text


@pytest.mark.asyncio
async def test_stream_cancellation_propagates_and_restores_principal(
    client: tuple[httpx.AsyncClient, _Provider, _Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http, provider, _ = client
    entered = asyncio.Event()
    closed = asyncio.Event()

    async def stalled(request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        try:
            principal = get_provider_principal()
            assert principal is not None and principal.user_id == "alice"
            entered.set()
            await asyncio.Event().wait()
            yield StreamEvent(
                kind="completed",
                request_id=request.request_id,
                sequence=0,
                model=DEFAULT_MODEL_ALIAS,
            )
        finally:
            closed.set()

    async def send() -> httpx.Response:
        try:
            return await http.post(
                "/v1/completions/stream",
                headers={"Authorization": "Bearer service-secret"},
                json={"context": _context(), "input": _completion_input()},
            )
        finally:
            assert get_provider_principal() is None

    monkeypatch.setattr(provider, "astream", stalled)
    async with http:
        task = asyncio.create_task(send())
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
        finally:
            task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert closed.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/v1/completions",
        "/v1/completions/stream",
        "/v1/provider-keys/list",
        "/v1/settings/read",
    ],
)
async def test_malformed_request_json_is_normalized(
    client: tuple[httpx.AsyncClient, _Provider, _Settings],
    path: str,
) -> None:
    http, provider, _ = client
    async with http:
        response = await http.post(
            path,
            headers={"Authorization": "Bearer service-secret"},
            content=b'{"sk-do-not-leak":',
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_context"
    assert "sk-do-not-leak" not in response.text
    assert provider.completion_calls == provider.stream_calls == 0
