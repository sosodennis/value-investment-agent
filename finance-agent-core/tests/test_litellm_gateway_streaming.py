import httpx
import pytest
from _llm_provider_test_helpers import _provider, _request

import src.llm_provider.infrastructure.gateway as gateway_module
from src.llm_provider.entrypoint import (
    CompletionRequest,
    LLMErrorCode,
    LLMProviderError,
    LLMRequestClass,
    ResolvedModelRoute,
    StreamEvent,
)
from src.llm_provider.infrastructure.gateway import (
    LiteLLMGatewayConfig,
    LiteLLMGatewayProvider,
)


def test_stream_cancellation_is_counted_and_not_swallowed() -> None:
    stream = (
        'data: {"model":"openrouter/free","choices":[{"delta":{"content":"one"}}]}\n\n'
        'data: {"model":"openrouter/free","choices":[{"delta":{"content":"two"}}]}\n\n'
        "data: [DONE]\n\n"
    )
    provider = _provider(
        httpx.MockTransport(
            lambda request: httpx.Response(200, text=stream, request=request)
        )
    )
    events = provider.stream(_request())
    assert next(events).kind == "started"
    assert next(events).text == "one"
    events.close()

    snapshot = provider.telemetry.snapshot()
    assert snapshot.requests == 1
    assert snapshot.streams == 1
    assert snapshot.failures == 1
    assert snapshot.stream_interruptions == 1


def test_stream_requires_a_completion_marker() -> None:
    provider = _provider(
        httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text='data: {"choices":[{"delta":{"content":"done?"}}]}\n\n',
                request=request,
            )
        )
    )

    with pytest.raises(LLMProviderError) as raised:
        list(provider.stream(_request()))

    assert raised.value.code is LLMErrorCode.STREAM_INTERRUPTED
    assert raised.value.partial_output == "done?"


def test_stream_usage_only_chunk_is_recorded() -> None:
    stream = (
        'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
        'data: {"choices":[],"usage":{"prompt_tokens":2,"completion_tokens":1,"total_tokens":3}}\n\n'
    )
    provider = _provider(
        httpx.MockTransport(
            lambda request: httpx.Response(200, text=stream, request=request)
        )
    )
    events = list(provider.stream(_request()))

    assert events[-1].kind == "completed"
    assert events[-1].usage is not None
    assert events[-1].usage.total_tokens == 3
    assert provider.telemetry.snapshot().total_tokens == 3


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


def test_stream_obeys_request_class_and_global_retry_budgets() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            503,
            json={"error": {"message": "temporarily unavailable"}},
            request=request,
        )

    provider = _provider(
        httpx.MockTransport(handler),
        config=LiteLLMGatewayConfig(
            base_url="http://gateway",
            api_key="gateway-key",
            max_attempts=2,
            attempts_by_request_class=(
                (LLMRequestClass.INTERACTIVE, 1),
                (LLMRequestClass.BACKGROUND, 3),
            ),
            backoff_seconds=0,
            jitter_seconds=0,
        ),
    )

    with pytest.raises(LLMProviderError) as interactive_error:
        list(provider.stream(_request(LLMRequestClass.INTERACTIVE)))
    assert interactive_error.value.attempt == 1
    assert attempts == 1

    with pytest.raises(LLMProviderError) as background_error:
        list(provider.stream(_request(LLMRequestClass.BACKGROUND)))
    assert background_error.value.attempt == 2
    assert attempts == 3


@pytest.mark.asyncio
async def test_async_stream_obeys_request_class_and_global_retry_budgets() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            503,
            json={"error": {"message": "temporarily unavailable"}},
            request=request,
        )

    provider = _provider(
        httpx.MockTransport(handler),
        config=LiteLLMGatewayConfig(
            base_url="http://gateway",
            api_key="gateway-key",
            max_attempts=2,
            attempts_by_request_class=(
                (LLMRequestClass.INTERACTIVE, 1),
                (LLMRequestClass.BACKGROUND, 3),
            ),
            backoff_seconds=0,
            jitter_seconds=0,
        ),
    )

    with pytest.raises(LLMProviderError) as interactive_error:
        async for _ in provider.astream(_request(LLMRequestClass.INTERACTIVE)):
            pass
    assert interactive_error.value.attempt == 1
    assert attempts == 1

    with pytest.raises(LLMProviderError) as background_error:
        async for _ in provider.astream(_request(LLMRequestClass.BACKGROUND)):
            pass
    assert background_error.value.attempt == 2
    assert attempts == 3
    await provider.aclose()


@pytest.mark.asyncio
async def test_async_stream_aclose_records_cancellation() -> None:
    stream = (
        'data: {"model":"openrouter/free","choices":[{"delta":{"content":"one"}}]}\n\n'
        "data: [DONE]\n\n"
    )
    provider = _provider(
        httpx.MockTransport(
            lambda request: httpx.Response(200, text=stream, request=request)
        )
    )
    events = provider.astream(_request())

    assert (await anext(events)).kind == "started"
    await events.aclose()

    snapshot = provider.telemetry.snapshot()
    assert snapshot.requests == 1
    assert snapshot.streams == 1
    assert snapshot.failures == 1
    assert snapshot.stream_interruptions == 1
    await provider.aclose()


@pytest.mark.asyncio
async def test_async_stream_records_time_to_first_token() -> None:
    stream = (
        'data: {"model":"openrouter/free","choices":[{"delta":{"content":"one"}}]}\n\n'
        "data: [DONE]\n\n"
    )
    provider = _provider(
        httpx.MockTransport(
            lambda request: httpx.Response(200, text=stream, request=request)
        )
    )

    events = [event async for event in provider.astream(_request())]

    assert [event.kind for event in events] == ["started", "delta", "completed"]
    snapshot = provider.telemetry.snapshot()
    assert snapshot.successes == 1
    assert snapshot.total_time_to_first_token_ms > 0
    await provider.aclose()


@pytest.mark.asyncio
async def test_interrupted_async_stream_records_time_to_first_token() -> None:
    stream = (
        'data: {"model":"openrouter/free","choices":[{"delta":{"content":"partial"}}]}\n\n'
        'data: {"broken":\n\n'
    )
    provider = _provider(
        httpx.MockTransport(
            lambda request: httpx.Response(200, text=stream, request=request)
        )
    )

    with pytest.raises(LLMProviderError) as raised:
        async for _ in provider.astream(_request()):
            pass

    assert raised.value.code is LLMErrorCode.STREAM_INTERRUPTED
    assert raised.value.partial_output == "partial"
    snapshot = provider.telemetry.snapshot()
    assert snapshot.failures == 1
    assert snapshot.total_time_to_first_token_ms > 0
    await provider.aclose()
