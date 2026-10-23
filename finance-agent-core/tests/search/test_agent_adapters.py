from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from src.agents.intent.application.ports import IntentWebSearchResult
from src.agents.intent.infrastructure.search import search_web_provider
from src.agents.news.domain.search_strategy.contracts import SearchTask
from src.agents.news.infrastructure.search import search_news_provider
from src.search import SearchClientError
from src.search.contracts import (
    NewsSearchRequest,
    SearchOperationResult,
    SearchResult,
    WebSearchRequest,
)


class _FakeSearchClient:
    def __init__(self, result: SearchOperationResult) -> None:
        self.result = result
        self.requests: list[NewsSearchRequest] = []

    def search_web(self, request: WebSearchRequest) -> SearchOperationResult:
        self.web_request = request
        return self.result

    async def search_news(self, request: NewsSearchRequest) -> SearchOperationResult:
        self.requests.append(request)
        return self.result


def _result(operation: str) -> SearchOperationResult:
    return SearchOperationResult(
        operation=operation,
        results=(
            SearchResult(
                title="Quarterly results",
                canonical_url="https://example.test/story",
                snippet="Revenue increased.",
                provider="fake",
                source="Example News",
                published_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
            ),
        ),
    )


def test_intent_adapter_preserves_ticker_expansion_and_maps_search_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeSearchClient(_result("web"))
    monkeypatch.setattr(search_web_provider, "get_search_client", lambda: fake)

    actual = search_web_provider.web_search("AAPL ticker")

    assert isinstance(actual, IntentWebSearchResult)
    assert actual.failure_code is None
    assert "Quarterly results" in actual.content
    assert fake.web_request.query == "AAPL ticker share classes tickers"


def test_intent_adapter_degrades_when_query_exceeds_service_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual = search_web_provider.web_search("x" * 600)

    assert actual.content == ""
    assert actual.failure_code == "INTENT_WEB_SEARCH_FAILED"
    assert actual.fallback_mode == "yahoo_only"


@pytest.mark.asyncio
async def test_news_adapter_keeps_task_limit_timeframe_and_normalized_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeSearchClient(_result("news"))
    monkeypatch.setattr(search_news_provider, "get_search_client", lambda: fake)
    monkeypatch.setattr(search_news_provider, "JITTER_SECONDS", (0.0, 0.0))

    task = SearchTask(
        time_param="w",
        query="AAPL earnings trusted sources",
        limit=4,
        tag="trusted_news",
    )
    rows = await search_news_provider._fetch_one_managed(task, asyncio.Semaphore(1))

    assert fake.requests == [
        NewsSearchRequest(
            query="AAPL earnings trusted sources",
            result_limit=4,
            region="worldwide",
            safe_search=False,
            time_range="week",
        )
    ]
    assert rows[0]["url"] == "https://example.test/story"
    assert rows[0]["_time_frame"] == "w"
    assert rows[0]["_search_tag"] == "trusted_news"


@pytest.mark.asyncio
async def test_news_adapter_retries_transient_failure_then_uses_query_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FallbackClient(_FakeSearchClient):
        async def search_news(
            self, request: NewsSearchRequest
        ) -> SearchOperationResult:
            self.requests.append(request)
            if len(self.requests) == 1:
                raise SearchClientError("UPSTREAM_UNAVAILABLE", "down", retryable=True)
            if len(self.requests) == 2:
                raise SearchClientError(
                    "UPSTREAM_UNAVAILABLE", "still down", retryable=True
                )
            return self.result

    fake = FallbackClient(_result("news"))
    monkeypatch.setattr(search_news_provider, "get_search_client", lambda: fake)
    monkeypatch.setattr(search_news_provider, "JITTER_SECONDS", (0.0, 0.0))
    rows = await search_news_provider._fetch_one_managed(
        SearchTask(
            time_param="m",
            query="initial query",
            limit=8,
            tag="bearish",
            fallbacks=("fallback query",),
        ),
        asyncio.Semaphore(1),
    )

    assert [request.query for request in fake.requests] == [
        "initial query",
        "initial query",
        "fallback query",
    ]
    assert [request.result_limit for request in fake.requests] == [8, 8, 8]
    assert rows[0]["_search_tag"] == "bearish"
