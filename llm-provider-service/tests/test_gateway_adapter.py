from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
import pytest
from src.llm_provider_service.application.context import (
    reset_provider_principal,
    set_provider_principal,
)
from src.llm_provider_service.domain.contracts import (
    ChatMessage,
    ChatRole,
    CompletionRequest,
    CompletionResult,
    LLMErrorCode,
    LLMProviderError,
    LLMRequestClass,
    ModelRoute,
    ProviderPrincipal,
)
from src.llm_provider_service.domain.routes import DEFAULT_MODEL_ALIAS, user_route_alias
from src.llm_provider_service.infrastructure.gateway import (
    LiteLLMGatewayConfig,
    LiteLLMGatewayProvider,
)
from src.llm_provider_service.infrastructure.telemetry import LLMProviderTelemetry


def _request() -> CompletionRequest:
    return CompletionRequest(
        messages=(ChatMessage(role=ChatRole.USER, content="hello"),),
        route=ModelRoute(alias=DEFAULT_MODEL_ALIAS),
        request_id="request-120",
        operation="adapter-test",
        request_class=LLMRequestClass.INTERACTIVE,
        temperature=0.25,
        max_tokens=32,
        timeout_seconds=2.0,
        idempotency_key="idem-120",
    )


def _config(*, attempts: int = 2) -> LiteLLMGatewayConfig:
    return LiteLLMGatewayConfig(
        base_url="https://gateway.test/v1",
        api_key="gateway-token",
        max_attempts=attempts,
        attempts_by_request_class=(
            (LLMRequestClass.INTERACTIVE, attempts),
            (LLMRequestClass.BACKGROUND, attempts),
        ),
        backoff_seconds=0,
        max_backoff_seconds=0,
        jitter_seconds=0,
        require_principal=True,
    )


def _completion_payload() -> dict[str, object]:
    return {
        "id": "completion-1",
        "model": "resolved-model",
        "choices": [
            {
                "message": {"role": "assistant", "content": "hello back"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
    }


@pytest.mark.asyncio
async def test_completion_uses_user_route_and_normalized_gateway_wire_contract() -> (
    None
):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=_completion_payload(),
            headers={
                "x-litellm-model-id": "deployment-7",
                "x-litellm-key-fingerprint": "abcdef012345",
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://gateway.test/v1",
    )
    telemetry = LLMProviderTelemetry()
    provider = LiteLLMGatewayProvider(
        _config(), async_client=client, telemetry=telemetry
    )
    results: list[CompletionResult] = []
    try:
        for user_id in ("alice", "bob"):
            principal_token = set_provider_principal(ProviderPrincipal(user_id=user_id))
            try:
                results.append(await provider.acomplete(_request()))
            finally:
                reset_provider_principal(principal_token)
    finally:
        await provider.aclose()
        await client.aclose()

    result = results[0]
    assert result.text == "hello back"
    assert result.usage is not None and result.usage.total_tokens == 6
    assert result.attribution is not None
    assert result.attribution.deployment_id == "deployment-7"
    assert result.attribution.key_fingerprint == "abcdef012345"
    assert len(requests) == 2
    sent = requests[0]
    assert sent.url == "https://gateway.test/v1/chat/completions"
    assert sent.headers["Authorization"] == "Bearer gateway-token"
    assert sent.headers["X-Request-ID"] == "request-120"
    assert sent.headers["Idempotency-Key"] == "idem-120"
    body = json.loads(sent.content)
    assert [json.loads(request.content)["model"] for request in requests] == [
        user_route_alias("alice"),
        user_route_alias("bob"),
    ]
    assert body["model"] != DEFAULT_MODEL_ALIAS
    assert body["messages"] == [{"role": "user", "content": "hello"}]
    assert body["max_tokens"] == 32
    snapshot = telemetry.snapshot()
    assert (snapshot.requests, snapshot.successes, snapshot.failures) == (2, 2, 0)
    assert (snapshot.attempts, snapshot.retries, snapshot.total_tokens) == (2, 0, 12)


@pytest.mark.asyncio
async def test_rate_limit_retries_once_and_records_sanitized_attempts() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                429,
                json={"error": "sk-upstream-secret"},
                headers={
                    "Retry-After": "0",
                    "x-litellm-model-id": "17",
                    "x-litellm-key-fingerprint": "0123456789ab",
                },
            )
        return httpx.Response(200, json=_completion_payload())

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://gateway.test/v1",
    )
    provider = LiteLLMGatewayProvider(_config(), async_client=client)
    principal_token = set_provider_principal(ProviderPrincipal(user_id="alice"))
    try:
        result = await provider.acomplete(_request())
    finally:
        reset_provider_principal(principal_token)
        await provider.aclose()
        await client.aclose()

    assert len(requests) == 2
    assert result.attempt == 2
    assert [attempt.error_code for attempt in result.attempts] == [
        LLMErrorCode.RATE_LIMITED.value,
        None,
    ]
    assert result.attempts[0].deployment_id == "17"
    assert result.attempts[0].key_fingerprint == "0123456789ab"


@pytest.mark.parametrize(
    ("request_class", "expected_attempts"),
    [
        (LLMRequestClass.INTERACTIVE, 2),
        (LLMRequestClass.BACKGROUND, 3),
    ],
)
@pytest.mark.asyncio
async def test_retryable_status_stops_at_request_class_budget(
    request_class: LLMRequestClass,
    expected_attempts: int,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            503,
            json={"detail": "sk-upstream-secret"},
            headers={"Retry-After": "0"},
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://gateway.test/v1",
    )
    config = LiteLLMGatewayConfig(
        base_url="https://gateway.test/v1",
        api_key="gateway-token",
        max_attempts=3,
        backoff_seconds=0,
        max_backoff_seconds=0,
        jitter_seconds=0,
        require_principal=True,
    )
    telemetry = LLMProviderTelemetry()
    provider = LiteLLMGatewayProvider(config, async_client=client, telemetry=telemetry)
    request = _request().model_copy(update={"request_class": request_class})
    principal_token = set_provider_principal(ProviderPrincipal(user_id="alice"))
    try:
        with pytest.raises(LLMProviderError) as raised:
            await provider.acomplete(request)
    finally:
        reset_provider_principal(principal_token)
        await provider.aclose()
        await client.aclose()

    error = raised.value
    assert len(requests) == expected_attempts
    assert error.code == LLMErrorCode.UPSTREAM_UNAVAILABLE
    assert error.http_status == 503
    assert error.retryable is False
    assert len(error.attempts) == expected_attempts
    assert all(
        attempt.error_code == LLMErrorCode.UPSTREAM_UNAVAILABLE.value
        for attempt in error.attempts
    )
    assert "sk-upstream-secret" not in str(error)
    snapshot = telemetry.snapshot()
    assert snapshot.attempts == expected_attempts
    assert snapshot.retries == expected_attempts - 1


@pytest.mark.asyncio
async def test_bad_request_is_not_retried_or_exposed_with_upstream_body() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(400, json={"detail": "sk-private-upstream-value"})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://gateway.test/v1",
    )
    telemetry = LLMProviderTelemetry()
    provider = LiteLLMGatewayProvider(
        _config(), async_client=client, telemetry=telemetry
    )
    principal_token = set_provider_principal(ProviderPrincipal(user_id="alice"))
    try:
        with pytest.raises(LLMProviderError) as raised:
            await provider.acomplete(_request())
    finally:
        reset_provider_principal(principal_token)
        await provider.aclose()
        await client.aclose()

    error = raised.value
    assert error.code == LLMErrorCode.BAD_REQUEST
    assert error.retryable is False
    assert "sk-private-upstream-value" not in str(error)
    assert "gateway rejected the request" in str(error)
    assert len(requests) == 1
    snapshot = telemetry.snapshot()
    assert (snapshot.requests, snapshot.successes, snapshot.failures) == (1, 0, 1)
    assert (snapshot.attempts, snapshot.retries) == (1, 0)


@pytest.mark.asyncio
async def test_stream_emits_normalized_events_and_counts_usage() -> None:
    requests: list[httpx.Request] = []
    chunks = (
        {
            "model": "resolved-model",
            "choices": [{"delta": {"content": "streamed"}}],
        },
        {
            "model": "resolved-model",
            "choices": [],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        },
    )
    content = "\n\n".join(f"data: {json.dumps(chunk)}" for chunk in chunks).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=content)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://gateway.test/v1",
    )
    telemetry = LLMProviderTelemetry()
    provider = LiteLLMGatewayProvider(
        _config(), async_client=client, telemetry=telemetry
    )
    principal_token = set_provider_principal(ProviderPrincipal(user_id="alice"))
    try:
        events = [event async for event in provider.astream(_request())]
    finally:
        reset_provider_principal(principal_token)
        await provider.aclose()
        await client.aclose()

    assert [(event.kind, event.sequence) for event in events] == [
        ("started", 0),
        ("delta", 1),
        ("completed", 2),
    ]
    assert events[1].text == "streamed"
    assert events[2].usage is not None and events[2].usage.total_tokens == 5
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert body["stream"] is True
    assert body["stream_options"] == {"include_usage": True}
    snapshot = telemetry.snapshot()
    assert (snapshot.requests, snapshot.streams, snapshot.successes) == (1, 1, 1)
    assert (
        snapshot.prompt_tokens,
        snapshot.completion_tokens,
        snapshot.total_tokens,
    ) == (
        3,
        2,
        5,
    )


class _InterruptedStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'data: {"model":"resolved-model","choices":[{"delta":{"content":"partial"}}]}\n\n'
        raise httpx.ReadError("sk-stream-secret")

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_interrupted_stream_surfaces_partial_output_without_replay() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, stream=_InterruptedStream())

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://gateway.test/v1",
    )
    telemetry = LLMProviderTelemetry()
    provider = LiteLLMGatewayProvider(
        _config(), async_client=client, telemetry=telemetry
    )
    principal_token = set_provider_principal(ProviderPrincipal(user_id="alice"))
    try:
        with pytest.raises(LLMProviderError) as raised:
            _ = [event async for event in provider.astream(_request())]
    finally:
        reset_provider_principal(principal_token)
        await provider.aclose()
        await client.aclose()

    error = raised.value
    assert error.code == LLMErrorCode.STREAM_INTERRUPTED
    assert error.partial_output == "partial"
    assert "sk-stream-secret" not in str(error)
    assert len(requests) == 1
    snapshot = telemetry.snapshot()
    assert (snapshot.requests, snapshot.streams, snapshot.failures) == (1, 1, 1)
    assert snapshot.stream_interruptions == 1
