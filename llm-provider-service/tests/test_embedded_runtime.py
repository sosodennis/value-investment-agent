from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace

import litellm
import pytest
from pydantic import BaseModel
from src.llm_provider_service.application.context import (
    reset_provider_principal,
    set_provider_principal,
)
from src.llm_provider_service.domain.contracts import (
    ChatMessage,
    ChatRole,
    CompletionRequest,
    LLMProviderError,
    ModelRoute,
    ProviderPrincipal,
    StreamEvent,
    StructuredRequest,
)
from src.llm_provider_service.domain.errors import (
    OpenRouterKeyTestError,
    ProviderSettingsError,
)
from src.llm_provider_service.domain.routes import (
    DEFAULT_MODEL_ALIAS,
    organization_route_alias,
)
from src.llm_provider_service.infrastructure.embedded_runtime import (
    EmbeddedLiteLLMProvider,
)
from src.llm_provider_service.infrastructure.state import ProviderDeployment


def _deployment(organization_id: str, identifier: str = "key-1") -> ProviderDeployment:
    return ProviderDeployment(
        id=identifier,
        organization_id=organization_id,
        label="primary",
        suffix="1234",
        fingerprint="abcdef012345",
        model="openrouter/free",
        created_at=datetime.now(UTC).isoformat(),
        status="healthy",
        failure_count=0,
        cooldown_until=None,
        last_tested_at=None,
        last_used_at=None,
        replacement_retire_at=None,
    )


class _State:
    def __init__(self) -> None:
        self.items = [_deployment("org-a")]
        self.keys = {"key-1": "sk-alice"}

    async def list_deployments(self, *, organization_id: str):
        return [item for item in self.items if item.organization_id == organization_id]

    async def deployment_key(self, *, organization_id: str, deployment_id: str) -> str:
        _ = organization_id
        return self.keys[deployment_id]

    async def get_deployment(self, *, organization_id: str, deployment_id: str):
        return next(
            (
                item
                for item in self.items
                if item.id == deployment_id and item.organization_id == organization_id
            ),
            None,
        )


class _Redis:
    def __init__(self) -> None:
        self.revision = 0

    async def ping(self) -> bool:
        return True

    async def get(self, key: str) -> str:
        _ = key
        return str(self.revision)

    async def incr(self, key: str) -> int:
        _ = key
        self.revision += 1
        return self.revision

    async def aclose(self) -> None:
        return None


class _Router:
    instances: list[_Router] = []
    calls: list[tuple[str, bool]] = []
    kwargs_calls: list[dict[str, object]] = []
    stream_failure = False

    def __init__(self, *, model_list, **kwargs) -> None:
        self.model_list = model_list
        self.kwargs = kwargs
        self.__class__.instances.append(self)

    async def acompletion(self, *, model: str, stream: bool = False, **kwargs):
        self.__class__.calls.append((model, stream))
        self.__class__.kwargs_calls.append(kwargs)
        if stream:
            return self._stream()
        return SimpleNamespace(
            model="openrouter/free",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="answer", tool_calls=[]),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

    async def _stream(self) -> AsyncIterator[object]:
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(delta=SimpleNamespace(content="partial", tool_calls=[]))
            ]
        )
        if self.stream_failure:
            raise RuntimeError("provider failure")


def _request() -> CompletionRequest:
    return CompletionRequest(
        messages=(ChatMessage(role=ChatRole.USER, content="hello"),),
        route=ModelRoute(alias=DEFAULT_MODEL_ALIAS),
        request_id="embedded-1",
        operation="test",
        timeout_seconds=2,
    )


def _runtime(monkeypatch: pytest.MonkeyPatch) -> EmbeddedLiteLLMProvider:
    monkeypatch.setattr("litellm.Router", _Router)
    _Router.calls.clear()
    _Router.kwargs_calls.clear()
    return EmbeddedLiteLLMProvider(_State(), redis_client=_Redis())


@pytest.mark.asyncio
async def test_embedded_runtime_uses_user_scoped_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER_KEY_COOLDOWN_SECONDS", "1")
    runtime = _runtime(monkeypatch)
    await runtime.start()
    token = set_provider_principal(
        ProviderPrincipal(
            user_id="alice", organization_id="org-a", membership_id="membership-a"
        )
    )
    try:
        result = await runtime.acomplete(_request())
    finally:
        reset_provider_principal(token)
        await runtime.aclose()
    assert result.text == "answer"
    assert _Router.calls == [(organization_route_alias("org-a"), False)]
    assert (
        _Router.instances[-1].model_list[0]["litellm_params"]["api_key"] == "sk-alice"
    )
    assert _Router.instances[-1].kwargs["fallbacks"] == []
    assert _Router.instances[-1].kwargs["max_fallbacks"] == 0


@pytest.mark.asyncio
async def test_embedded_runtime_stream_surfaces_interruption_without_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _Router.stream_failure = True
    runtime = _runtime(monkeypatch)
    await runtime.start()
    token = set_provider_principal(
        ProviderPrincipal(
            user_id="alice", organization_id="org-a", membership_id="membership-a"
        )
    )
    try:
        events: list[StreamEvent] = []
        with pytest.raises(LLMProviderError) as caught:
            async for event in runtime.astream(_request()):
                events.append(event)
    finally:
        reset_provider_principal(token)
        _Router.stream_failure = False
        await runtime.aclose()
    assert [event.kind for event in events] == ["started", "delta"]
    assert caught.value.code.value == "stream_interrupted"
    assert _Router.calls == [(organization_route_alias("org-a"), True)]
    assert caught.value.attempts[0].error_code == "upstream_unavailable"


@pytest.mark.asyncio
async def test_embedded_runtime_forwards_request_identity_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(monkeypatch)
    await runtime.start()
    token = set_provider_principal(
        ProviderPrincipal(
            user_id="alice", organization_id="org-a", membership_id="membership-a"
        )
    )
    request = _request().model_copy(
        update={
            "idempotency_key": "idem-1",
            "metadata": {"workflow": "debate"},
        }
    )
    try:
        await runtime.acomplete(request)
    finally:
        reset_provider_principal(token)
        await runtime.aclose()
    kwargs = _Router.kwargs_calls[-1]
    assert kwargs["metadata"] == {
        "workflow": "debate",
        "request_id": "embedded-1",
        "operation": "test",
    }
    assert kwargs["extra_headers"] == {
        "X-Request-ID": "embedded-1",
        "Idempotency-Key": "idem-1",
    }


@pytest.mark.asyncio
async def test_embedded_runtime_preserves_key_validation_error_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(monkeypatch)
    await runtime.start()
    token = set_provider_principal(
        ProviderPrincipal(
            user_id="alice", organization_id="org-a", membership_id="membership-a"
        )
    )

    async def rate_limited(_key: str) -> None:
        raise OpenRouterKeyTestError("rate_limited", retry_after_seconds=2)

    monkeypatch.setattr(
        "src.llm_provider_service.infrastructure.openrouter_key_test.validate_openrouter_key",
        rate_limited,
    )
    try:
        with pytest.raises(ProviderSettingsError) as caught:
            await runtime.test_key("key-1", organization_id="org-a")
    finally:
        reset_provider_principal(token)
        await runtime.aclose()

    assert caught.value.code == "rate_limited"


@pytest.mark.asyncio
async def test_embedded_runtime_retries_before_first_stream_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RetryRouter(_Router):
        stream_calls = 0

        async def acompletion(self, *, model: str, stream: bool = False, **kwargs):
            if stream:
                type(self).stream_calls += 1
                if type(self).stream_calls == 1:

                    async def failed():
                        raise RuntimeError("transient")
                        yield  # pragma: no cover

                    return failed()
            return await super().acompletion(model=model, stream=stream, **kwargs)

    monkeypatch.setattr("litellm.Router", RetryRouter)
    monkeypatch.setattr(
        "src.llm_provider_service.infrastructure.embedded_runtime.asyncio.sleep",
        lambda _delay: _completed_sleep(),
    )
    runtime = EmbeddedLiteLLMProvider(_State(), redis_client=_Redis())
    await runtime.start()
    token = set_provider_principal(
        ProviderPrincipal(
            user_id="alice", organization_id="org-a", membership_id="membership-a"
        )
    )
    try:
        events = [event async for event in runtime.astream(_request())]
    finally:
        reset_provider_principal(token)
        await runtime.aclose()
    assert RetryRouter.stream_calls == 2
    assert [event.kind for event in events] == ["started", "delta", "completed"]
    assert [event.sequence for event in events] == [0, 1, 2]


async def _completed_sleep() -> None:
    return None


@pytest.mark.asyncio
async def test_embedded_runtime_requires_an_authenticated_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(monkeypatch)
    await runtime.start()
    with pytest.raises(LLMProviderError) as caught:
        await runtime.acomplete(_request())
    await runtime.aclose()
    assert caught.value.code.value == "provider_context_missing"


@pytest.mark.asyncio
async def test_embedded_runtime_preserves_terminal_attempt_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RateLimited(Exception):
        status_code = 429

    class FailingRouter(_Router):
        async def acompletion(self, *, model: str, stream: bool = False, **kwargs):
            raise RateLimited("too many requests")

    monkeypatch.setattr("litellm.Router", FailingRouter)
    monkeypatch.setattr(
        "src.llm_provider_service.infrastructure.embedded_runtime.asyncio.sleep",
        lambda _delay: _completed_sleep(),
    )
    runtime = EmbeddedLiteLLMProvider(_State(), redis_client=_Redis())
    await runtime.start()
    token = set_provider_principal(
        ProviderPrincipal(
            user_id="alice", organization_id="org-a", membership_id="membership-a"
        )
    )
    try:
        with pytest.raises(LLMProviderError) as caught:
            await runtime.acomplete(_request())
    finally:
        reset_provider_principal(token)
        await runtime.aclose()
    assert caught.value.code.value == "rate_limited"
    assert caught.value.retryable is False
    assert [item.error_code for item in caught.value.attempts] == [
        "rate_limited",
        "rate_limited",
    ]


@pytest.mark.asyncio
async def test_embedded_runtime_rejects_malformed_completion_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MalformedRouter(_Router):
        async def acompletion(self, *, model: str, stream: bool = False, **kwargs):
            return SimpleNamespace(model="openrouter/free", choices=[])

    runtime = EmbeddedLiteLLMProvider(_State(), redis_client=_Redis())
    monkeypatch.setattr("litellm.Router", MalformedRouter)
    await runtime.start()
    token = set_provider_principal(
        ProviderPrincipal(
            user_id="alice", organization_id="org-a", membership_id="membership-a"
        )
    )
    try:
        with pytest.raises(LLMProviderError) as caught:
            await runtime.acomplete(_request())
    finally:
        reset_provider_principal(token)
        await runtime.aclose()
    assert caught.value.code.value == "malformed_response"
    assert len(caught.value.attempts) == 1


@pytest.mark.asyncio
async def test_embedded_runtime_fails_closed_when_redis_is_unavailable() -> None:
    class BrokenRedis(_Redis):
        async def ping(self) -> bool:
            raise ConnectionError("redis unavailable")

    runtime = EmbeddedLiteLLMProvider(_State(), redis_client=BrokenRedis())
    with pytest.raises(ConnectionError, match="redis unavailable"):
        await runtime.start()
    await runtime.aclose()


@pytest.mark.asyncio
async def test_real_litellm_router_receives_provider_deployment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[dict[str, object]] = []

    async def fake_litellm_completion(**kwargs):
        observed.append(kwargs)
        return SimpleNamespace(
            model=kwargs["model"],
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="router-ok", tool_calls=[]),
                    finish_reason="stop",
                )
            ],
        )

    async def fake_redis_ping(_self):
        return True

    monkeypatch.setattr(litellm, "acompletion", fake_litellm_completion)
    monkeypatch.setattr("litellm.caching.redis_cache.RedisCache.ping", fake_redis_ping)
    runtime = EmbeddedLiteLLMProvider(_State(), redis_client=_Redis())
    await runtime.start()
    token = set_provider_principal(
        ProviderPrincipal(
            user_id="alice", organization_id="org-a", membership_id="membership-a"
        )
    )
    try:
        result = await runtime.acomplete(_request())
    finally:
        reset_provider_principal(token)
        await runtime.aclose()
    assert result.text == "router-ok"
    assert observed[0]["model"] == "openrouter/free"
    assert observed[0]["api_key"] == "sk-alice"
    assert observed[0]["api_base"] == "https://openrouter.ai/api/v1"


@pytest.mark.asyncio
async def test_embedded_runtime_corrects_invalid_structured_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Answer(BaseModel):
        value: int

    class StructuredRouter(_Router):
        structured_calls = 0

        async def acompletion(self, *, model: str, stream: bool = False, **kwargs):
            if not stream:
                type(self).structured_calls += 1
                value = (
                    '{"value":"bad"}'
                    if type(self).structured_calls == 1
                    else '{"value":7}'
                )
                return SimpleNamespace(
                    model="openrouter/free",
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content=value, tool_calls=[]),
                            finish_reason="stop",
                        )
                    ],
                )
            return await super().acompletion(model=model, stream=stream, **kwargs)

    monkeypatch.setattr("litellm.Router", StructuredRouter)
    runtime = EmbeddedLiteLLMProvider(_State(), redis_client=_Redis())
    await runtime.start()
    token = set_provider_principal(
        ProviderPrincipal(
            user_id="alice", organization_id="org-a", membership_id="membership-a"
        )
    )
    try:
        result = await runtime.acomplete_structured(
            StructuredRequest(completion=_request(), response_schema=Answer)
        )
    finally:
        reset_provider_principal(token)
        await runtime.aclose()
    assert result.value == 7
    assert StructuredRouter.structured_calls == 2
