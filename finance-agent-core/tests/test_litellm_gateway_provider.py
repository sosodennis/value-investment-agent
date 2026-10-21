import json

import httpx
import pytest
from pydantic import BaseModel

import src.infrastructure.llm.gateway as gateway_module
from src.infrastructure.llm.gateway import LiteLLMGatewayConfig, LiteLLMGatewayProvider
from src.infrastructure.llm.provider import get_default_model_route
from src.shared.llm.context import reset_provider_principal, set_provider_principal
from src.shared.llm.contracts import (
    ChatMessage,
    ChatRole,
    CompletionRequest,
    LLMErrorCode,
    LLMProviderError,
    ModelRoute,
    ProviderPrincipal,
    ResolvedModelRoute,
    StreamEvent,
    StructuredRequest,
)


class _Answer(BaseModel):
    answer: str


def _request() -> CompletionRequest:
    return CompletionRequest(
        messages=(ChatMessage(role=ChatRole.USER, content="hello"),),
        route=ModelRoute(alias="openrouter-default"),
        request_id="req-1",
        operation="test",
    )


def _provider(
    handler: httpx.MockTransport, *, require_principal: bool = False
) -> LiteLLMGatewayProvider:
    client = httpx.Client(transport=handler, base_url="http://gateway/v1")
    async_client = httpx.AsyncClient(transport=handler, base_url="http://gateway/v1")
    return LiteLLMGatewayProvider(
        LiteLLMGatewayConfig(
            base_url="http://gateway",
            api_key="gateway-key",
            max_attempts=2,
            backoff_seconds=0,
            require_principal=require_principal,
        ),
        client=client,
        async_client=async_client,
    )


def test_default_route_is_not_changed_by_legacy_model_environment(monkeypatch) -> None:
    monkeypatch.setenv("DEFAULT_LLM_MODEL", "openrouter/some-paid-model")
    monkeypatch.setenv("LLM_MODEL_ALIAS", "caller-controlled-alias")

    assert get_default_model_route().alias == "openrouter-default"


def test_production_adapter_requires_an_authenticated_provider_principal() -> None:
    provider = _provider(
        httpx.MockTransport(lambda request: httpx.Response(500)),
        require_principal=True,
    )

    with pytest.raises(LLMProviderError) as error:
        provider.complete(_request())

    assert error.value.code is LLMErrorCode.PROVIDER_CONTEXT_MISSING


def test_authenticated_users_resolve_to_distinct_gateway_pools() -> None:
    models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        models.append(payload["model"])
        return httpx.Response(
            200,
            json={
                "model": "openrouter/free",
                "choices": [{"message": {"content": "ok"}}],
            },
            request=request,
        )

    provider = _provider(httpx.MockTransport(handler), require_principal=True)
    for user_id in ("user-a", "user-b"):
        token = set_provider_principal(ProviderPrincipal(user_id=user_id))
        try:
            provider.complete(_request())
        finally:
            reset_provider_principal(token)

    assert len(models) == 2
    assert models[0].startswith("openrouter-user-")
    assert models[0] != models[1]


def test_complete_maps_openai_response_and_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer gateway-key"
        assert request.headers["x-request-id"] == "req-1"
        assert (
            request.read()
            == b'{"model":"openrouter-default","messages":[{"role":"user","content":"hello"}],"temperature":0.0,"stream":false}'
        )
        return httpx.Response(
            200,
            json={
                "model": "openrouter/auto",
                "choices": [
                    {
                        "message": {"content": "hello back"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 2,
                    "completion_tokens": 3,
                    "total_tokens": 5,
                },
            },
            request=request,
        )

    provider = _provider(httpx.MockTransport(handler))
    result = provider.complete(_request())

    assert result.text == "hello back"
    assert result.model == "openrouter/auto"
    assert result.usage is not None
    assert result.usage.total_tokens == 5


def test_complete_retries_transient_gateway_failure_once() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                503, json={"error": {"message": "busy"}}, request=request
            )
        return httpx.Response(
            200,
            json={
                "model": "openrouter/auto",
                "choices": [{"message": {"content": "ok"}}],
            },
            request=request,
        )

    provider = _provider(httpx.MockTransport(handler))

    assert provider.complete(_request()).text == "ok"
    assert attempts == 2


def test_complete_records_sanitized_attempt_attribution() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                503,
                headers={
                    "x-litellm-model-id": "deployment-1",
                    "x-key-fingerprint": "sha256:0123456789abcdef",
                },
                json={"error": {"message": "temporary failure"}},
                request=request,
            )
        return httpx.Response(
            200,
            headers={
                "x-litellm-model-id": "deployment-2",
                "x-key-fingerprint": "sha256:fedcba9876543210",
            },
            json={
                "model": "openrouter/free",
                "choices": [{"message": {"content": "ok"}}],
            },
            request=request,
        )

    result = _provider(httpx.MockTransport(handler)).complete(_request())

    assert [item.attempt for item in result.attempts] == [1, 2]
    assert result.attempts[0].deployment_id == "deployment-1"
    assert result.attempts[0].error_code == "upstream_unavailable"
    assert result.attempts[1].deployment_id == "deployment-2"
    assert result.attempts[1].error_code is None
    assert result.attribution is not None
    assert result.attribution.key_fingerprint == "sha256:fedcba9876543210"


def test_exhausted_gateway_retries_return_attempted_metadata_without_secrets() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            429,
            headers={
                "x-litellm-model-id": f"deployment-{calls}",
                "x-key-fingerprint": "sha256:0123456789abcdef",
            },
            json={"error": {"message": "key sk-or-v1-secret"}},
            request=request,
        )

    provider = LiteLLMGatewayProvider(
        LiteLLMGatewayConfig(
            base_url="http://gateway",
            api_key="gateway-key",
            max_attempts=2,
            backoff_seconds=0,
            jitter_seconds=0,
        ),
        client=httpx.Client(
            transport=httpx.MockTransport(handler), base_url="http://gateway/v1"
        ),
        async_client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://gateway/v1"
        ),
    )

    with pytest.raises(LLMProviderError) as raised:
        provider.complete(_request())

    assert calls == 2
    assert raised.value.attempt == 2
    assert [item.deployment_id for item in raised.value.attempts] == [
        "deployment-1",
        "deployment-2",
    ]
    assert all(
        item.key_fingerprint == "sha256:0123456789abcdef"
        for item in raised.value.attempts
    )
    assert "sk-or-v1-secret" not in str(raised.value)


def test_complete_honors_bounded_retry_after_delay(monkeypatch) -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "30"},
                json={"error": {"message": "rate limited"}},
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "model": "openrouter/auto",
                "choices": [{"message": {"content": "ok"}}],
            },
            request=request,
        )

    monkeypatch.setattr(gateway_module.time, "sleep", delays.append)
    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://gateway/v1"
    )
    provider = LiteLLMGatewayProvider(
        LiteLLMGatewayConfig(
            base_url="http://gateway",
            api_key="gateway-key",
            max_attempts=2,
            backoff_seconds=0.25,
            max_backoff_seconds=2.0,
        ),
        client=client,
        async_client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://gateway/v1"
        ),
    )

    assert provider.complete(_request()).text == "ok"
    assert attempts == 2
    assert delays == [2.0]


def test_gateway_retry_configuration_has_a_hard_attempt_ceiling(monkeypatch) -> None:
    monkeypatch.setenv("LLM_GATEWAY_MAX_ATTEMPTS", "99")

    config = LiteLLMGatewayConfig.from_env()

    assert config.max_attempts == 3
    with pytest.raises(ValueError, match="between 1 and 3"):
        LiteLLMGatewayConfig(
            base_url="http://gateway",
            api_key="gateway-key",
            max_attempts=4,
        )


def test_complete_does_not_retry_authentication_failure() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            401,
            json={"error": {"message": "invalid gateway key"}},
            request=request,
        )

    provider = _provider(httpx.MockTransport(handler))

    with pytest.raises(LLMProviderError) as raised:
        provider.complete(_request())

    assert raised.value.code is LLMErrorCode.AUTHENTICATION_FAILED
    assert raised.value.retryable is False
    assert raised.value.reason == "gateway authentication failed"
    assert "invalid gateway key" not in raised.value.reason
    assert attempts == 1


def test_sync_structured_completion_validates_and_sends_schema() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        assert '"response_format"' in body
        assert '"name":"_Answer"' in body
        return httpx.Response(
            200,
            json={
                "model": "openrouter/auto",
                "choices": [{"message": {"content": '{"answer":"ok"}'}}],
            },
            request=request,
        )

    provider = _provider(httpx.MockTransport(handler))
    result = provider.complete_structured(
        StructuredRequest[_Answer](completion=_request(), response_schema=_Answer)
    )

    assert result.answer == "ok"


@pytest.mark.asyncio
async def test_structured_completion_validates_pydantic_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "openrouter/auto",
                "choices": [{"message": {"content": '{"answer":"ok"}'}}],
            },
            request=request,
        )

    provider = _provider(httpx.MockTransport(handler))
    result = await provider.acomplete_structured(
        StructuredRequest[_Answer](completion=_request(), response_schema=_Answer)
    )

    assert result.answer == "ok"
    await provider.aclose()


@pytest.mark.asyncio
async def test_structured_request_sends_json_schema_to_gateway() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        assert '"response_format"' in body
        assert '"name":"_Answer"' in body
        return httpx.Response(
            200,
            json={
                "model": "openrouter/auto",
                "choices": [{"message": {"content": '{"answer":"ok"}'}}],
            },
            request=request,
        )

    provider = _provider(httpx.MockTransport(handler))
    result = await provider.acomplete_structured(
        StructuredRequest[_Answer](completion=_request(), response_schema=_Answer)
    )

    assert result.answer == "ok"
    await provider.aclose()


def test_stream_emits_ordered_events() -> None:
    stream = (
        'data: {"model":"openrouter/auto","choices":[{"delta":{"content":"hel"}}]}\n\n'
        'data: {"model":"openrouter/auto","choices":[{"delta":{"content":"lo"}}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=stream,
            headers={"content-type": "text/event-stream"},
            request=request,
        )

    provider = _provider(httpx.MockTransport(handler))
    events = list(provider.stream(_request()))

    assert [event.kind for event in events] == [
        "started",
        "delta",
        "delta",
        "completed",
    ]
    assert "".join(event.text for event in events if event.kind == "delta") == "hello"
    assert [event.sequence for event in events] == [0, 1, 2, 3]


def test_stream_does_not_retry_after_first_delta() -> None:
    stream = (
        'data: {"model":"openrouter/auto","choices":[{"delta":{"content":"partial"}}]}\n\n'
        'data: {"broken":\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=stream,
            headers={"content-type": "text/event-stream"},
            request=request,
        )

    provider = _provider(httpx.MockTransport(handler))

    with pytest.raises(LLMProviderError) as raised:
        list(provider.stream(_request()))

    assert raised.value.code is LLMErrorCode.STREAM_INTERRUPTED
    assert raised.value.partial_output == "partial"
    assert [item.attempt for item in raised.value.attempts] == [1]


def test_stream_error_preserves_delivered_tool_calls() -> None:
    stream = (
        'data: {"model":"openrouter/auto","choices":[{"delta":{"tool_calls":[{"id":"call-1"}]}}]}\n\n'
        'data: {"broken":\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=stream, request=request)

    provider = _provider(httpx.MockTransport(handler))

    with pytest.raises(LLMProviderError) as raised:
        list(provider.stream(_request()))

    assert raised.value.code is LLMErrorCode.STREAM_INTERRUPTED
    assert raised.value.partial_tool_calls == ({"id": "call-1"},)
    assert [item.attempt for item in raised.value.attempts] == [1]


def test_stream_provider_error_after_first_delta_has_one_terminal_attempt(
    monkeypatch,
) -> None:
    stream = (
        'data: {"model":"openrouter/auto","choices":[{"delta":{"content":"partial"}}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=stream, request=request)

    original = gateway_module.LiteLLMGatewayProvider._stream_event_from_line
    calls = 0

    def fail_after_delta(
        self: LiteLLMGatewayProvider,
        line: str,
        request: CompletionRequest,
        attempt: int,
        model: str,
        sequence: int,
        resolved_route: ResolvedModelRoute,
    ) -> StreamEvent | None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise LLMProviderError(
                code=LLMErrorCode.UPSTREAM_UNAVAILABLE,
                provider="litellm-gateway",
                model=model,
                request_id=request.request_id,
                reason="synthetic stream failure",
                retryable=False,
                attempt=attempt,
            )
        return original(self, line, request, attempt, model, sequence, resolved_route)

    monkeypatch.setattr(
        gateway_module.LiteLLMGatewayProvider,
        "_stream_event_from_line",
        fail_after_delta,
    )

    provider = _provider(httpx.MockTransport(handler))

    with pytest.raises(LLMProviderError) as raised:
        list(provider.stream(_request()))

    assert raised.value.code is LLMErrorCode.STREAM_INTERRUPTED
    assert [item.attempt for item in raised.value.attempts] == [1]


def test_stream_can_retry_before_first_delta() -> None:
    attempts = 0
    stream = 'data: {"model":"openrouter/auto","choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                503, json={"error": {"message": "busy"}}, request=request
            )
        return httpx.Response(200, text=stream, request=request)

    provider = _provider(httpx.MockTransport(handler))
    events = list(provider.stream(_request()))

    assert attempts == 2
    assert "".join(event.text for event in events if event.kind == "delta") == "ok"
