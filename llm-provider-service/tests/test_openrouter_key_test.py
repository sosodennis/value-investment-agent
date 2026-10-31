from __future__ import annotations

import httpx
import pytest
from src.llm_provider_service.domain.errors import OpenRouterKeyTestError
from src.llm_provider_service.infrastructure.openrouter_key_test import (
    validate_openrouter_key,
)


@pytest.mark.asyncio
async def test_validation_uses_authenticated_current_key_endpoint() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": {"label": "staging"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await validate_openrouter_key("sk-or-test-key-material", client=client)

    assert len(requests) == 1
    assert requests[0].url.path == "/api/v1/key"
    assert requests[0].headers["Authorization"] == "Bearer sk-or-test-key-material"


@pytest.mark.asyncio
async def test_validation_rejects_invalid_credentials() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(401))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(OpenRouterKeyTestError) as caught:
            await validate_openrouter_key("sk-or-test-key-material", client=client)

    assert str(caught.value) == "invalid_key"


@pytest.mark.asyncio
async def test_validation_classifies_rate_limit_as_retryable() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(429, headers={"Retry-After": "2"})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(OpenRouterKeyTestError) as caught:
            await validate_openrouter_key("sk-or-test-key-material", client=client)

    assert str(caught.value) == "rate_limited"
    assert caught.value.retry_after_seconds == 2


@pytest.mark.asyncio
async def test_validation_classifies_timeout_and_upstream_failure_as_retryable() -> (
    None
):
    async def timeout(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("request timed out")

    for transport in (
        httpx.MockTransport(timeout),
        httpx.MockTransport(lambda _request: httpx.Response(503)),
    ):
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(OpenRouterKeyTestError) as caught:
                await validate_openrouter_key("sk-or-test-key-material", client=client)
        assert caught.value.code == "upstream_unavailable"


@pytest.mark.asyncio
async def test_validation_treats_other_client_errors_as_permanent_rejections() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(404))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(OpenRouterKeyTestError) as caught:
            await validate_openrouter_key("sk-or-test-key-material", client=client)
    assert caught.value.code == "request_rejected"
