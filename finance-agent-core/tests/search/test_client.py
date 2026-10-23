from __future__ import annotations

import json

import httpx
import pytest

from src.llm_provider.entrypoint import (
    ProviderPrincipal,
    reset_provider_principal,
    set_provider_principal,
)
from src.search import (
    NewsSearchRequest,
    SearchClient,
    SearchClientError,
    SearchClientSettings,
    WebSearchRequest,
)


def _client(handler: httpx.MockTransport) -> SearchClient:
    settings = SearchClientSettings(
        base_url="https://search.test",
        service_token="test-token",
        subject_id="test-user",
    )
    return SearchClient(
        settings,
        client=httpx.Client(transport=handler),
        async_client=httpx.AsyncClient(transport=handler),
    )


def test_web_operation_sends_frozen_policy_and_parses_empty_success() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "contract_version": "internal.v1",
                "correlation_id": body["context"]["correlation_id"],
                "result": {"operation": "web", "results": []},
            },
        )

    result = _client(httpx.MockTransport(respond)).search_web(
        WebSearchRequest(query="  AAPL stock  ")
    )

    assert result.results == ()
    assert requests[0].url.path == "/v1/search/web"
    assert requests[0].headers["authorization"] == "Bearer test-token"
    sent = json.loads(requests[0].content)
    assert sent["context"]["principal"]["subject_id"] == "test-user"
    assert sent["input"] == {
        "query": "AAPL stock",
        "result_limit": 7,
        "region": "en-US",
        "time_range": "year",
        "safe_search": True,
        "timeout_seconds": 30,
    }


@pytest.mark.asyncio
async def test_news_operation_sends_worldwide_week_limit_and_safe_search_off() -> None:
    captured: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "contract_version": "internal.v1",
                "correlation_id": body["context"]["correlation_id"],
                "result": {"operation": "news", "results": []},
            },
        )

    await _client(httpx.MockTransport(respond)).search_news(
        NewsSearchRequest(query="AAPL earnings", result_limit=4, time_range="week")
    )
    sent = json.loads(captured[0].content)
    assert captured[0].url.path == "/v1/search/news"
    assert sent["input"]["region"] == "worldwide"
    assert sent["input"]["safe_search"] is False
    assert sent["input"]["time_range"] == "week"
    assert sent["input"]["result_limit"] == 4


def test_client_rejects_wrong_correlation_and_malformed_responses() -> None:
    client = _client(
        httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "contract_version": "internal.v1",
                    "correlation_id": "wrong",
                    "result": {"operation": "web", "results": []},
                },
            )
        )
    )

    with pytest.raises(SearchClientError) as caught:
        client.search_web(WebSearchRequest(query="AAPL"))
    assert caught.value.code == "UPSTREAM_MALFORMED"


def test_client_maps_service_error_envelope() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            503,
            json={
                "contract_version": "internal.v1",
                "correlation_id": body["context"]["correlation_id"],
                "error": {
                    "code": "UPSTREAM_UNAVAILABLE",
                    "message": "providers unavailable",
                    "retryable": True,
                },
            },
        )

    with pytest.raises(SearchClientError) as caught:
        _client(httpx.MockTransport(respond)).search_web(WebSearchRequest(query="AAPL"))
    assert caught.value.code == "UPSTREAM_UNAVAILABLE"
    assert caught.value.retryable


def test_client_maps_transport_timeout() -> None:
    client = _client(
        httpx.MockTransport(
            lambda _request: (_ for _ in ()).throw(httpx.ReadTimeout("late"))
        )
    )

    with pytest.raises(SearchClientError) as caught:
        client.search_web(WebSearchRequest(query="AAPL"))
    assert caught.value.code == "DEADLINE_EXCEEDED"
    assert not caught.value.retryable


def test_authenticated_request_principal_overrides_standalone_subject() -> None:
    seen: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body["context"]["principal"]["subject_id"])
        return httpx.Response(
            200,
            json={
                "contract_version": "internal.v1",
                "correlation_id": body["context"]["correlation_id"],
                "result": {"operation": "web", "results": []},
            },
        )

    token = set_provider_principal(ProviderPrincipal(user_id="alice"))
    try:
        _client(httpx.MockTransport(respond)).search_web(WebSearchRequest(query="AAPL"))
    finally:
        reset_provider_principal(token)

    assert seen == ["alice"]
