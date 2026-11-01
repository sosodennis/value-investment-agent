from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import pytest

from src.search import (
    NewsSearchRequest,
    SearchClient,
    SearchClientError,
    SearchClientSettings,
    WebSearchRequest,
)
from src.shared.internal_services import (
    InternalPrincipal,
    reset_request_principal,
    set_request_principal,
)
from src.shared.kernel.correlation import reset_correlation_id, set_correlation_id


def _client(handler: httpx.MockTransport) -> SearchClient:
    settings = SearchClientSettings(
        base_url="https://search.test",
        service_token="test-token",
    )
    return SearchClient(
        settings,
        client=httpx.Client(transport=handler),
        async_client=httpx.AsyncClient(transport=handler),
    )


@contextmanager
def _request_principal(subject_id: str = "test-user") -> Iterator[None]:
    token = set_request_principal(InternalPrincipal(subject_id=subject_id))
    try:
        yield
    finally:
        reset_request_principal(token)


@contextmanager
def _correlation_id(value: str = "trace-search") -> Iterator[None]:
    token = set_correlation_id(value)
    try:
        yield
    finally:
        reset_correlation_id(token)


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

    with _request_principal(), _correlation_id():
        result = _client(httpx.MockTransport(respond)).search_web(
            WebSearchRequest(query="  AAPL stock  ")
        )

    assert result.results == ()
    assert requests[0].url.path == "/v1/search/web"
    assert requests[0].headers["authorization"] == "Bearer test-token"
    assert requests[0].headers["x-request-id"] == "trace-search"
    sent = json.loads(requests[0].content)
    assert sent["context"]["correlation_id"] == "trace-search"
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

    with _request_principal(), _correlation_id("trace-news"):
        await _client(httpx.MockTransport(respond)).search_news(
            NewsSearchRequest(query="AAPL earnings", result_limit=4, time_range="week")
        )
    assert captured[0].headers["x-request-id"] == "trace-news"
    sent = json.loads(captured[0].content)
    assert sent["context"]["correlation_id"] == "trace-news"
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

    with _request_principal(), pytest.raises(SearchClientError) as caught:
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

    with _request_principal(), pytest.raises(SearchClientError) as caught:
        _client(httpx.MockTransport(respond)).search_web(WebSearchRequest(query="AAPL"))
    assert caught.value.code == "UPSTREAM_UNAVAILABLE"
    assert caught.value.retryable


def test_client_maps_transport_timeout() -> None:
    client = _client(
        httpx.MockTransport(
            lambda _request: (_ for _ in ()).throw(httpx.ReadTimeout("late"))
        )
    )

    with _request_principal(), pytest.raises(SearchClientError) as caught:
        client.search_web(WebSearchRequest(query="AAPL"))
    assert caught.value.code == "DEADLINE_EXCEEDED"
    assert not caught.value.retryable


def test_authenticated_request_principal_is_sent_to_search_service() -> None:
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

    with _request_principal("alice"):
        _client(httpx.MockTransport(respond)).search_web(WebSearchRequest(query="AAPL"))

    assert seen == ["alice"]


def test_search_client_rejects_missing_request_principal_before_transport() -> None:
    requests: list[httpx.Request] = []
    client = _client(
        httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(200, json={})
        )
    )

    with pytest.raises(SearchClientError) as caught:
        client.search_web(WebSearchRequest(query="AAPL"))

    assert caught.value.code == "AUTHENTICATION_FAILED"
    assert requests == []
