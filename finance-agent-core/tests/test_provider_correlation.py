from __future__ import annotations

import json

import httpx
import pytest

from src.llm_provider.infrastructure.remote_client import (
    LLMProviderServiceSettingsClient,
)
from src.search_settings.infrastructure.client import SearchServiceClient
from src.shared.kernel.correlation import reset_correlation_id, set_correlation_id


def _with_correlation(value: str):
    token = set_correlation_id(value)
    return token


@pytest.mark.asyncio
async def test_llm_settings_client_forwards_request_correlation() -> None:
    seen: list[dict[str, object]] = []
    seen_headers: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        seen_headers.append(request.headers["X-Request-ID"])
        return httpx.Response(
            200,
            json={
                "contract_version": "internal.v1",
                "correlation_id": body["context"]["correlation_id"],
                "result": {"keys": []},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    service = LLMProviderServiceSettingsClient(
        base_url="http://llm.test", token="private-token", client=client
    )
    token = _with_correlation("request-llm-210")
    try:
        assert (
            await service.list_keys(
                user_id="user-1",
                organization_id="organization-1",
                membership_id="membership-1",
            )
            == []
        )
    finally:
        reset_correlation_id(token)
        await service.aclose()
        await client.aclose()

    assert seen[0]["context"]["correlation_id"] == "request-llm-210"
    assert seen_headers == ["request-llm-210"]


@pytest.mark.asyncio
async def test_search_settings_client_forwards_request_correlation() -> None:
    seen: list[dict[str, object]] = []
    seen_headers: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        seen_headers.append(request.headers["X-Request-ID"])
        return httpx.Response(
            200,
            json={
                "contract_version": "internal.v1",
                "correlation_id": body["context"]["correlation_id"],
                "result": {"catalog": {"providers": []}},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    service = SearchServiceClient(
        base_url="http://search.test", token="private-token", client=client
    )
    token = _with_correlation("request-search-210")
    try:
        assert (
            await service.catalog(
                principal="user-1",
                organization_id="org-alpha",
                membership_id="membership-alpha",
            )
            == []
        )
    finally:
        reset_correlation_id(token)
        await service.aclose()
        await client.aclose()

    assert seen[0]["context"]["correlation_id"] == "request-search-210"
    assert seen_headers == ["request-search-210"]
