from __future__ import annotations

import asyncio
import traceback
from collections.abc import Iterator

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
    answer: int


@pytest.fixture
def principal() -> Iterator[None]:
    token = set_provider_principal(
        ProviderPrincipal(
            user_id="alice",
            organization_id="organization-a",
            membership_id="membership-a",
        )
    )
    try:
        yield
    finally:
        reset_provider_principal(token)


def _request() -> CompletionRequest:
    return CompletionRequest(
        messages=(ChatMessage(role="user", content="private-query"),),
        route=ModelRoute(alias="openrouter-default"),
        request_id="parse-120",
        operation="test",
    )


def _client(body: bytes, status: int = 200) -> LLMProviderServiceClient:
    client = LLMProviderServiceClient(
        base_url="http://provider.test", token="private-token"
    )
    client._client.close()
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, content=body)
    )
    client._client = httpx.Client(transport=transport)
    client._async_client = httpx.AsyncClient(transport=transport)
    return client


def _assert_error(error: LLMProviderError, code: LLMErrorCode) -> None:
    assert error.code is code
    assert error.request_id == "parse-120"
    assert "sk-private-response" not in "".join(traceback.format_exception(error))


@pytest.mark.parametrize(
    "body",
    [
        b"not-json-sk-private-response",
        b"[]",
        b'{"result":{}}',
        b'{"result":{"request_id":123,"text":"sk-private-response"}}',
    ],
)
def test_invalid_completion_envelopes_are_safe_typed_errors(
    body: bytes, principal: None
) -> None:
    client = _client(body)
    try:
        with pytest.raises(LLMProviderError) as caught:
            client.complete(_request())
        _assert_error(caught.value, LLMErrorCode.MALFORMED_RESPONSE)
    finally:
        asyncio.run(client.aclose())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body", [b"not-json-sk-private-response", b"null", b'{"result":{}}']
)
async def test_invalid_async_completion_envelopes_are_safe_typed_errors(
    body: bytes, principal: None
) -> None:
    client = _client(body)
    try:
        with pytest.raises(LLMProviderError) as caught:
            await client.acomplete(_request())
        _assert_error(caught.value, LLMErrorCode.MALFORMED_RESPONSE)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_structured_schema_errors_are_normalized_for_both_clients(
    principal: None,
) -> None:
    client = _client(
        b'{"result":{"request_id":"parse-120","text":"{\\"answer\\":\\"sk-private-response\\"}","model":"openrouter-default"}}'
    )
    request = StructuredRequest(completion=_request(), response_schema=_Answer)
    try:
        with pytest.raises(LLMProviderError) as caught:
            client.complete_structured(request)
        _assert_error(caught.value, LLMErrorCode.SCHEMA_VALIDATION_FAILED)
        with pytest.raises(LLMProviderError) as caught:
            await client.acomplete_structured(request)
        _assert_error(caught.value, LLMErrorCode.SCHEMA_VALIDATION_FAILED)
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "frame",
    [
        b"data: sk-private-response\n\n",
        b"data: {}\n\n",
        b'data: {"event":{"kind":"invalid","text":"sk-private-response"}}\n\n',
    ],
)
async def test_malformed_stream_frames_are_typed_for_sync_and_async(
    frame: bytes, principal: None
) -> None:
    client = _client(frame)
    try:
        with pytest.raises(LLMProviderError) as caught:
            list(client.stream(_request()))
        _assert_error(caught.value, LLMErrorCode.MALFORMED_RESPONSE)
        with pytest.raises(LLMProviderError) as caught:
            async for _event in client.astream(_request()):
                pass
        _assert_error(caught.value, LLMErrorCode.MALFORMED_RESPONSE)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_service_deadline_is_a_timeout_including_stream_http_error(
    principal: None,
) -> None:
    client = _client(
        b'{"error":{"code":"deadline_exceeded","message":"sk-private-response","retryable":true}}',
        504,
    )
    try:
        with pytest.raises(LLMProviderError) as caught:
            client.complete(_request())
        _assert_error(caught.value, LLMErrorCode.UPSTREAM_TIMEOUT)
        with pytest.raises(LLMProviderError) as caught:
            list(client.stream(_request()))
        _assert_error(caught.value, LLMErrorCode.UPSTREAM_TIMEOUT)
        with pytest.raises(LLMProviderError) as caught:
            async for _event in client.astream(_request()):
                pass
        _assert_error(caught.value, LLMErrorCode.UPSTREAM_TIMEOUT)
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        b"[]",
        b'{"result":{"keys":null}}',
        b'{"result":{"keys":[{"failure_count":"sk-private-response"}]}}',
    ],
)
async def test_malformed_settings_do_not_escape_parser_errors(body: bytes) -> None:
    client = LLMProviderServiceSettingsClient(
        base_url="http://provider.test", token="private-token"
    )
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    )
    try:
        with pytest.raises(ProviderSettingsError) as caught:
            await client.list_keys(
                user_id="alice",
                organization_id="organization-a",
                membership_id="membership-a",
            )
        assert caught.value.code == "provider_unavailable"
        assert "sk-private-response" not in "".join(
            traceback.format_exception(caught.value)
        )
    finally:
        await client.aclose()
