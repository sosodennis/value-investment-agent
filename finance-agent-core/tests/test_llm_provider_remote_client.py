from __future__ import annotations

import asyncio
import traceback
from collections.abc import Awaitable, Callable

import httpx
import pytest
from pydantic import BaseModel

from src.llm_provider.application.context import (
    reset_provider_principal,
    set_provider_principal,
)
from src.llm_provider.domain.contracts import (
    ChatMessage,
    CompletionRequest,
    LLMErrorCode,
    LLMProviderError,
    ModelRoute,
    ProviderPrincipal,
    StructuredRequest,
)
from src.llm_provider.domain.errors import ProviderSettingsError
from src.llm_provider.infrastructure.remote_client import (
    LLMProviderServiceClient,
    LLMProviderServiceSettingsClient,
)


class _Answer(BaseModel):
    answer: str


def _request(*, content: str = "hello") -> CompletionRequest:
    return CompletionRequest(
        messages=(ChatMessage(role="user", content=content),),
        route=ModelRoute(alias="openrouter-default"),
        request_id="remote-120",
        operation="test",
    )


_PRIVATE_VALUES = (
    "http://provider.test",
    "private-token",
    "private-request-body",
)


def _failure_handler(
    error_type: type[httpx.TransportError],
) -> Callable[[httpx.Request], httpx.Response]:
    def fail(request: httpx.Request) -> httpx.Response:
        details = (
            f"url={request.url} authorization={request.headers['authorization']} "
            f"body={request.content.decode()}"
        )
        raise error_type(details, request=request)

    return fail


def _sync_client(error_type: type[httpx.TransportError]) -> LLMProviderServiceClient:
    client = LLMProviderServiceClient(
        base_url="http://provider.test", token="private-token"
    )
    client._client.close()
    client._client = httpx.Client(
        transport=httpx.MockTransport(_failure_handler(error_type)), timeout=None
    )
    return client


async def _async_client(
    error_type: type[httpx.TransportError],
) -> LLMProviderServiceClient:
    client = LLMProviderServiceClient(
        base_url="http://provider.test", token="private-token"
    )
    client._client.close()
    await client._async_client.aclose()
    client._async_client = httpx.AsyncClient(
        transport=httpx.MockTransport(_failure_handler(error_type)), timeout=None
    )
    return client


def _assert_safe_error(error: Exception) -> None:
    public_error = "".join(traceback.format_exception(error))
    assert all(value not in public_error for value in _PRIVATE_VALUES)


def test_structured_remote_call_forwards_schema_and_does_not_retry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = request.read()
        assert b'"response_schema"' in body
        assert request.headers["authorization"] == "Bearer internal-secret"
        return httpx.Response(
            200,
            json={
                "result": {
                    "request_id": "remote-120",
                    "text": '{"answer":"ok"}',
                    "model": "openrouter-default",
                }
            },
            request=request,
        )

    client = LLMProviderServiceClient(
        base_url="http://provider.test", token="internal-secret"
    )
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler), timeout=None)
    token = set_provider_principal(ProviderPrincipal(user_id="alice"))
    try:
        result = client.complete_structured(
            StructuredRequest(completion=_request(), response_schema=_Answer)
        )
    finally:
        reset_provider_principal(token)
        client._client.close()

    assert result == _Answer(answer="ok")
    assert calls == 1


def test_sync_provider_calls_map_transport_errors_without_leaking_details() -> None:
    client = _sync_client(httpx.ConnectError)
    token = set_provider_principal(ProviderPrincipal(user_id="alice"))
    try:
        calls: tuple[Callable[[], object], ...] = (
            lambda: client.complete(_request(content=_PRIVATE_VALUES[-1])),
            lambda: client.complete_structured(
                StructuredRequest(
                    completion=_request(content=_PRIVATE_VALUES[-1]),
                    response_schema=_Answer,
                )
            ),
            lambda: list(client.stream(_request(content=_PRIVATE_VALUES[-1]))),
        )
        for call in calls:
            try:
                call()
            except LLMProviderError as error:
                assert error.code is LLMErrorCode.UPSTREAM_UNAVAILABLE
                assert error.retryable is True
                assert error.reason == "provider service is unavailable"
                _assert_safe_error(error)
            else:
                raise AssertionError("provider transport failure was not mapped")
    finally:
        reset_provider_principal(token)
        asyncio.run(client.aclose())


@pytest.mark.asyncio
async def test_async_provider_calls_map_timeouts_without_leaking_details() -> None:
    client = await _async_client(httpx.ReadTimeout)
    token = set_provider_principal(ProviderPrincipal(user_id="alice"))

    async def consume_stream() -> None:
        async for _event in client.astream(_request(content=_PRIVATE_VALUES[-1])):
            pass

    calls: tuple[Callable[[], Awaitable[object]], ...] = (
        lambda: client.acomplete(_request(content=_PRIVATE_VALUES[-1])),
        lambda: client.acomplete_structured(
            StructuredRequest(
                completion=_request(content=_PRIVATE_VALUES[-1]),
                response_schema=_Answer,
            )
        ),
        consume_stream,
    )
    try:
        for call in calls:
            try:
                await call()
            except LLMProviderError as error:
                assert error.code is LLMErrorCode.UPSTREAM_TIMEOUT
                assert error.retryable is True
                assert error.reason == "provider service request timed out"
                _assert_safe_error(error)
            else:
                raise AssertionError("provider transport failure was not mapped")
    finally:
        reset_provider_principal(token)
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
async def test_settings_calls_map_transport_errors_without_leaking_details(
    error_type: type[httpx.TransportError],
) -> None:
    client = LLMProviderServiceSettingsClient(
        base_url="http://provider.test", token="private-token"
    )
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(_failure_handler(error_type)), timeout=None
    )
    try:
        with pytest.raises(ProviderSettingsError) as caught:
            await client.add_key(
                user_id="alice", key=_PRIVATE_VALUES[-1], label="primary"
            )
        assert caught.value.code == "provider_unavailable"
        _assert_safe_error(caught.value)
    finally:
        await client.aclose()


class _BlockingTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def handle_async_request(self, _request: httpx.Request) -> httpx.Response:
        self.started.set()
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_async_cancellation_propagates_without_transport_error_mapping() -> None:
    client = LLMProviderServiceClient(
        base_url="http://provider.test", token="internal-secret"
    )
    client._client.close()
    await client._async_client.aclose()
    transport = _BlockingTransport()
    client._async_client = httpx.AsyncClient(transport=transport, timeout=None)
    token = set_provider_principal(ProviderPrincipal(user_id="alice"))
    task = asyncio.create_task(client.acomplete(_request()))
    try:
        await asyncio.wait_for(transport.started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        reset_provider_principal(token)
        await client.aclose()


@pytest.mark.asyncio
async def test_settings_cancellation_propagates_without_transport_error_mapping() -> (
    None
):
    client = LLMProviderServiceSettingsClient(
        base_url="http://provider.test", token="private-token"
    )
    await client._client.aclose()
    transport = _BlockingTransport()
    client._client = httpx.AsyncClient(transport=transport, timeout=None)
    task = asyncio.create_task(client.list_keys(user_id="alice"))
    try:
        await asyncio.wait_for(transport.started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        await client.aclose()
