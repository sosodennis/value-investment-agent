from __future__ import annotations

import asyncio

from src.agents.news.application.analysis_service import (
    AnalysisChains,
    analyze_news_items,
    build_analysis_chains,
    run_analysis_with_resilience,
)
from src.agents.news.application.fetch_service import (
    build_articles_to_fetch,
    build_news_item_payload,
    build_news_items_from_fetch_results,
    parse_published_at,
)
from src.agents.news.application.ports import FetchContentResult
from src.agents.news.application.selection_service import (
    build_selector_degraded_indices,
    normalize_selected_indices,
    run_selector_with_resilience,
)
from src.agents.news.application.state_readers import aggregator_ticker_from_state
from src.agents.news.application.state_updates import (
    build_analyst_chain_error_update,
    build_analyst_node_error_update,
    build_analyst_node_update,
    build_fetch_node_error_update,
    build_fetch_node_update,
    build_search_node_empty_update,
    build_search_node_error_update,
    build_search_node_no_ticker_update,
    build_search_node_success_update,
    build_selector_node_error_update,
    build_selector_node_update,
)
from src.agents.news.application.use_cases.run_aggregator_node_use_case import (
    run_aggregator_node_use_case,
)
from src.agents.news.application.use_cases.run_fetch_node_use_case import (
    run_fetch_node_use_case,
)
from src.agents.news.application.use_cases.run_search_node_use_case import (
    run_search_node_use_case,
)
from src.agents.news.application.use_cases.run_selector_node_use_case import (
    run_selector_node_use_case,
)
from src.agents.news.domain.aggregation.aggregation_service import aggregate_news_items
from src.agents.news.domain.aggregation.summary_message_service import (
    build_news_summary_message,
)
from src.agents.news.domain.news_item_projection_service import to_news_item_entities
from src.agents.news.infrastructure.content_fetch.trafilatura_content_fetch_provider import (
    close_shared_async_client,
    get_shared_async_client,
)
from src.agents.news.infrastructure.ids.news_id_generator_service import (
    generate_news_id,
)
from src.agents.news.interface.contracts import (
    FinancialNewsItemModel,
    NewsSearchResultItemModel,
    SourceInfoModel,
)
from src.agents.news.interface.prompt_renderers import build_analysis_chain_payload


def test_aggregate_news_items_computes_weighted_sentiment_and_themes() -> None:
    news_items = [
        {
            "title": "A",
            "source": {"reliability_score": 0.9},
            "analysis": {
                "sentiment_score": 0.8,
                "key_event": "Earnings beat",
                "summary": "Positive earnings",
                "key_facts": [{"content": "EPS up"}],
            },
        },
        {
            "title": "B",
            "source": {"reliability_score": 0.3},
            "analysis": {
                "sentiment_score": -0.2,
                "key_event": "Minor risk",
                "summary": "Small risk",
                "key_facts": [],
            },
        },
    ]

    result = aggregate_news_items(to_news_item_entities(news_items), ticker="GME")

    assert result.sentiment_label == "bullish"
    assert result.weighted_score > 0.3
    assert "Earnings beat" in result.key_themes
    assert len(result.top_headlines) == 2


def test_build_news_summary_message_renders_expected_shape() -> None:
    result = aggregate_news_items([], ticker="GME")
    message = build_news_summary_message(ticker="GME", result=result)

    assert "### News Research: GME" in message
    assert "Overall Sentiment" in message
    assert "Themes:" in message


def test_build_articles_to_fetch_filters_out_of_range_indices() -> None:
    raw = [
        NewsSearchResultItemModel(
            title="A",
            source="Reuters",
            snippet="s",
            link="https://x.com/a",
            date="2026-02-13",
            categories=["general"],
        ),
        NewsSearchResultItemModel(
            title="B",
            source="Reuters",
            snippet="s",
            link="https://x.com/b",
            date="2026-02-13",
            categories=["general"],
        ),
    ]
    selected = build_articles_to_fetch(raw, [0, 2, 1])
    assert [item.title for item in selected] == ["A", "B"]


def test_build_news_item_payload_creates_canonical_item() -> None:
    payload = build_news_item_payload(
        result=NewsSearchResultItemModel(
            title="Test - Reuters",
            link="https://example.com/x",
            snippet="snippet",
            date="2026-02-13T10:00:00",
            categories=["general"],
            source="Reuters",
        ),
        full_content="full",
        content_id="artifact-x",
        generated_id="id-x",
        reliability_score=0.9,
        item_factory=FinancialNewsItemModel,
        source_factory=SourceInfoModel,
    )
    assert payload["id"] == "id-x"
    assert payload["content_id"] == "artifact-x"
    assert payload["full_content"] == "full"
    assert payload["source"]["name"] == "Reuters"


def test_build_analysis_chain_payload_uses_finbert_fields_when_present() -> None:
    payload = build_analysis_chain_payload(
        ticker="GME",
        item={"title": "A", "source": {"name": "Reuters"}, "categories": ["bullish"]},
        content_to_analyze="content",
        finbert_summary={
            "label": "positive",
            "confidence": "99.0%",
            "has_numbers": True,
        },
    )
    assert payload["search_tag"] == "BULLISH"
    assert payload["finbert_sentiment"] == "POSITIVE"
    assert payload["finbert_has_numbers"] == "Yes"


def test_update_payload_builders_include_error_log_when_needed() -> None:
    fetch_update = build_fetch_node_update(news_items_id="nid", article_errors=["err"])
    analyst_update = build_analyst_node_update(
        news_items_id="nid", article_errors=["e1", "e2"]
    )
    assert fetch_update["node_statuses"]["financial_news_research"] == "degraded"
    assert len(fetch_update["error_logs"]) == 1
    assert analyst_update["node_statuses"]["financial_news_research"] == "degraded"
    assert "Failed to analyze 2 articles" in analyst_update["error_logs"][0]["error"]


def test_node_update_builders_for_search_selector_and_analyst_chain() -> None:
    no_ticker = build_search_node_no_ticker_update()
    assert no_ticker["current_node"] == "search_node"
    assert no_ticker["node_statuses"]["financial_news_research"] == "done"

    search_error = build_search_node_error_update("boom")
    assert search_error["node_statuses"]["financial_news_research"] == "error"
    assert "Search failed" in search_error["error_logs"][0]["error"]

    empty = build_search_node_empty_update()
    assert empty["internal_progress"]["search_node"] == "done"
    assert empty["node_statuses"]["financial_news_research"] == "done"

    success = build_search_node_success_update(
        artifact={
            "kind": "financial_news_research.output",
            "version": "v1",
            "summary": "ok",
            "preview": None,
            "reference": None,
        },
        search_artifact_id="a1",
    )
    assert success["financial_news_research"]["search_artifact_id"] == "a1"
    assert success["node_statuses"]["financial_news_research"] == "running"

    selector_degraded = build_selector_node_update(
        selection_artifact_id="s1",
        is_degraded=True,
        error_message="x",
    )
    assert selector_degraded["node_statuses"]["financial_news_research"] == "degraded"
    selector_error = build_selector_node_error_update("selector failed")
    assert selector_error["node_statuses"]["financial_news_research"] == "error"

    fetch_error = build_fetch_node_error_update("fetch failed")
    assert fetch_error["node_statuses"]["financial_news_research"] == "error"

    analyst_error = build_analyst_node_error_update("analyst failed")
    assert analyst_error["node_statuses"]["financial_news_research"] == "error"

    analyst_chain_error = build_analyst_chain_error_update("chain boom")
    assert analyst_chain_error["node_statuses"]["financial_news_research"] == "error"
    assert (
        "Failed to create analysis chains"
        in analyst_chain_error["error_logs"][0]["error"]
    )


def test_parse_published_at_invalid_returns_none() -> None:
    assert parse_published_at("bad-date") is None


def test_build_selector_degraded_indices_returns_top_three() -> None:
    raw_results = [{"t": "A"}, {"t": "B"}, {"t": "C"}, {"t": "D"}]
    assert build_selector_degraded_indices(raw_results) == [0, 1, 2]


def test_normalize_selected_indices_deduplicates_and_limits() -> None:
    normalized = normalize_selected_indices([3, 1, 3, 2, 1], limit=3)
    assert normalized == [3, 1, 2]


class _FakeModel:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def model_dump(self, *, mode: str) -> dict[str, object]:
        assert mode == "json"
        return self._payload


class _GoodChain:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def invoke(self, payload: object) -> _FakeModel:
        _ = payload
        return _FakeModel(self._payload)


class _FailingChain:
    def invoke(self, payload: object) -> _FakeModel:
        _ = payload
        raise RuntimeError("chain failed")


class _FakePrompt:
    def __or__(self, rhs: object) -> object:
        return rhs


class _FakeLLM:
    def with_structured_output(self, schema: type[object]) -> object:
        _ = schema
        return _GoodChain({"summary": "ok"})


def test_build_analysis_chains_returns_two_invokable_chains() -> None:
    chains = build_analysis_chains(
        llm=_FakeLLM(),
        prompt_basic=_FakePrompt(),
        prompt_finbert=_FakePrompt(),
        analysis_model_type=object,
    )
    assert isinstance(chains, AnalysisChains)
    assert chains.basic.invoke({}).model_dump(mode="json")["summary"] == "ok"
    assert chains.finbert.invoke({}).model_dump(mode="json")["summary"] == "ok"


def test_run_analysis_with_resilience_uses_basic_when_finbert_chain_fails() -> None:
    chains = AnalysisChains(
        basic=_GoodChain({"source_chain": "basic"}),
        finbert=_FailingChain(),
    )
    payload, used_degraded_path = asyncio.run(
        run_analysis_with_resilience(
            chains=chains,
            chain_payload={"ticker": "GME"},
            prefer_finbert_chain=True,
        )
    )
    assert used_degraded_path is True
    assert payload["source_chain"] == "basic"


class _SelectorResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _SelectorChain:
    def __init__(self, content: str) -> None:
        self._content = content

    def invoke(self, payload: object) -> _SelectorResponse:
        _ = payload
        return _SelectorResponse(self._content)


def test_run_selector_with_resilience_parses_selected_urls() -> None:
    chain = _SelectorChain(
        '{"selected_articles":[{"url":"https://x.com/a"},{"url":"https://x.com/c"}]}'
    )
    result = asyncio.run(
        run_selector_with_resilience(
            chain=chain,
            ticker="GME",
            formatted_results="...",
            raw_results=[
                {"link": "https://x.com/a"},
                {"link": "https://x.com/b"},
                {"link": "https://x.com/c"},
            ],
        )
    )
    assert result.selected_indices == [0, 2]
    assert result.is_degraded is False


class _AsyncSelectorChain:
    def __init__(self, content: str) -> None:
        self._content = content
        self.ainvoke_called = False
        self.invoke_called = False

    async def ainvoke(self, payload: object) -> _SelectorResponse:
        _ = payload
        self.ainvoke_called = True
        return _SelectorResponse(self._content)

    def invoke(self, payload: object) -> _SelectorResponse:
        _ = payload
        self.invoke_called = True
        return _SelectorResponse(self._content)


def test_run_selector_with_resilience_prefers_ainvoke_when_available() -> None:
    chain = _AsyncSelectorChain(
        '{"selected_articles":[{"url":"https://x.com/a"},{"url":"https://x.com/b"}]}'
    )
    result = asyncio.run(
        run_selector_with_resilience(
            chain=chain,
            ticker="GME",
            formatted_results="...",
            raw_results=[
                {"link": "https://x.com/a"},
                {"link": "https://x.com/b"},
            ],
        )
    )
    assert result.selected_indices == [0, 1]
    assert chain.ainvoke_called is True
    assert chain.invoke_called is False


class _FakeNewsPort:
    async def save_news_article(
        self, *, data: dict[str, object], produced_by: str, key_prefix: str
    ) -> str:
        _ = data
        _ = produced_by
        _ = key_prefix
        return "content-artifact-1"

    async def load_news_article_text(self, content_id: object) -> str:
        _ = content_id
        return "full article text"


def test_build_news_items_from_fetch_results_creates_items() -> None:
    result = asyncio.run(
        build_news_items_from_fetch_results(
            articles_to_fetch=[
                NewsSearchResultItemModel(
                    title="News - Reuters",
                    link="https://x.com/a",
                    snippet="snippet",
                    date="2026-02-13T10:00:00",
                    categories=["general"],
                    source="Reuters",
                )
            ],
            full_contents=["full text"],
            ticker="GME",
            timestamp=123,
            port=_FakeNewsPort(),
            generate_news_id_fn=lambda _url, _title: "news-1",
            get_source_reliability_fn=lambda _url: 0.9,
            item_factory=FinancialNewsItemModel,
            source_factory=SourceInfoModel,
        )
    )
    assert len(result.news_items) == 1
    assert result.news_items[0]["content_id"] == "content-artifact-1"


class _NoFinbert:
    def is_available(self) -> bool:
        return False

    def analyze(self, content: str) -> None:
        _ = content
        return None


def test_analyze_news_items_sets_analysis_payload() -> None:
    result = asyncio.run(
        analyze_news_items(
            news_items=[
                {
                    "title": "A",
                    "snippet": "hello",
                    "source": {"name": "Reuters"},
                    "categories": ["general"],
                    "content_id": "content-artifact-1",
                }
            ],
            ticker="GME",
            port=_FakeNewsPort(),
            finbert_analyzer=_NoFinbert(),
            chains=AnalysisChains(
                basic=_GoodChain({"summary": "ok"}),
                finbert=_GoodChain({"summary": "ok"}),
            ),
        )
    )
    assert not result.article_errors
    assert result.news_items[0]["analysis"]["summary"] == "ok"


class _FetchUseCasePort:
    def __init__(self) -> None:
        self.saved_news_items: dict[str, object] | None = None

    async def load_fetch_context(
        self,
        search_artifact_id: str | None,
        selection_artifact_id: str | None,
    ) -> tuple[list[dict[str, object]], list[int]]:
        _ = search_artifact_id
        _ = selection_artifact_id
        return (
            [
                {
                    "title": "Good",
                    "source": "Reuters",
                    "snippet": "good snippet",
                    "link": "https://example.com/good",
                    "date": "2026-02-13T10:00:00",
                    "categories": ["general"],
                },
                {
                    "title": "Bad",
                    "source": "Reuters",
                    "snippet": "bad snippet",
                    "link": "https://example.com/bad",
                    "date": "2026-02-13T11:00:00",
                    "categories": ["general"],
                },
            ],
            [0, 1],
        )

    async def save_news_article(
        self,
        data: dict[str, object],
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        _ = data
        _ = produced_by
        return f"content-{key_prefix or 'x'}"

    async def save_news_items(
        self,
        data: dict[str, object],
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        _ = produced_by
        _ = key_prefix
        self.saved_news_items = data
        return "news-items-1"


def test_run_fetch_node_use_case_keeps_partial_success_when_one_fetch_fails() -> None:
    port = _FetchUseCasePort()

    async def _fetch(url: str) -> FetchContentResult:
        if url.endswith("/bad"):
            return FetchContentResult.fail(
                code="http_status",
                reason="non-200 response: 403",
                http_status=403,
            )
        return FetchContentResult.ok("full text ok")

    result = asyncio.run(
        run_fetch_node_use_case(
            state={
                "intent_extraction": {"resolved_ticker": "GOOG"},
                "financial_news_research": {
                    "search_artifact_id": "s1",
                    "selection_artifact_id": "sel1",
                },
            },
            port=port,
            fetch_clean_text_async_fn=_fetch,
            generate_news_id_fn=lambda url, title: f"id-{title or url or 'unknown'}",
            get_source_reliability_fn=lambda _url: 0.9,
            item_factory=FinancialNewsItemModel,
            source_factory=SourceInfoModel,
        )
    )

    assert result.goto == "analyst_node"
    assert result.update["node_statuses"]["financial_news_research"] == "degraded"
    assert "Content fetch degraded" in result.update["error_logs"][0]["error"]
    assert port.saved_news_items is not None
    saved_items = port.saved_news_items["news_items"]
    assert isinstance(saved_items, list)
    assert saved_items[0]["full_content"] == "full text ok"
    assert saved_items[1]["full_content"] is None


class _AggregatorLoadFailPort:
    async def load_news_items_data(
        self, news_items_artifact_id: str | None
    ) -> list[dict]:
        _ = news_items_artifact_id
        raise RuntimeError("load failed")


def test_run_aggregator_node_use_case_fails_fast_when_loading_news_items_fails() -> (
    None
):
    result = asyncio.run(
        run_aggregator_node_use_case(
            state={
                "ticker": "GOOG",
                "financial_news_research": {"news_items_artifact_id": "n1"},
            },
            port=_AggregatorLoadFailPort(),
            summarize_preview=lambda _ctx, _items: {},
            build_news_report_payload=lambda ticker, news_items, aggregation: {
                "ticker": ticker,
                "news_items": news_items,
                "overall_sentiment": aggregation.sentiment_label,
                "sentiment_score": aggregation.weighted_score,
                "key_themes": aggregation.key_themes,
            },
            build_output_artifact=lambda _summary, _preview, _report_id: None,
        )
    )

    assert result.goto == "END"
    assert result.update["internal_progress"]["aggregator_node"] == "error"
    assert result.update["node_statuses"]["financial_news_research"] == "error"
    assert "Failed to load news items" in result.update["error_logs"][0]["error"]


def test_generate_news_id_uses_title_when_url_is_missing() -> None:
    first = generate_news_id("", "Alpha headline")
    second = generate_news_id("", "Beta headline")

    assert first != second


def test_shared_async_client_is_reused_and_can_be_closed() -> None:
    async def _scenario() -> None:
        first = await get_shared_async_client()
        second = await get_shared_async_client()
        assert first is second

        await close_shared_async_client()
        assert first.is_closed

        third = await get_shared_async_client()
        assert third is not first
        await close_shared_async_client()

    asyncio.run(_scenario())


class _SelectorContextFailPort:
    async def load_search_context(
        self, search_artifact_id: str | None
    ) -> tuple[str, list[dict[str, object]]]:
        _ = search_artifact_id
        raise RuntimeError("context unavailable")

    async def save_news_selection(
        self,
        data: dict[str, object],
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        _ = data
        _ = produced_by
        _ = key_prefix
        return "selection-1"


def test_run_selector_node_use_case_marks_degraded_when_context_load_fails() -> None:
    llm_called = False

    def _get_llm() -> object:
        nonlocal llm_called
        llm_called = True
        raise AssertionError("LLM must not be called when selector context load fails")

    result = asyncio.run(
        run_selector_node_use_case(
            state={
                "intent_extraction": {"resolved_ticker": "GOOG"},
                "financial_news_research": {"search_artifact_id": "search-1"},
            },
            port=_SelectorContextFailPort(),
            get_llm_fn=_get_llm,
            selector_system_prompt="system",
            selector_user_prompt="user",
        )
    )

    assert llm_called is False
    assert result.goto == "END"
    assert result.update["node_statuses"]["financial_news_research"] == "error"
    assert "selector context" in result.update["error_logs"][0]["error"]


def test_aggregator_ticker_from_state_prefers_resolved_ticker() -> None:
    ticker = aggregator_ticker_from_state(
        {
            "ticker": "STATE_TICKER",
            "intent_extraction": {"resolved_ticker": "GOOG"},
        }
    )
    assert ticker == "GOOG"


def test_aggregator_ticker_from_state_does_not_fallback_to_root_ticker() -> None:
    ticker = aggregator_ticker_from_state({"ticker": "STATE_TICKER"})
    assert ticker == "UNKNOWN"


class _SearchSaveFailPort:
    async def save_search_results(
        self,
        data: dict[str, object],
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str:
        _ = data
        _ = produced_by
        _ = key_prefix
        raise RuntimeError("artifact save failed")


def test_run_search_node_use_case_stops_when_search_artifact_save_fails() -> None:
    result = asyncio.run(
        run_search_node_use_case(
            state={"intent_extraction": {"resolved_ticker": "GOOG"}},
            port=_SearchSaveFailPort(),
            build_output_artifact=lambda _summary, _preview, _report_id: None,
            news_search_multi_timeframe_fn=lambda _ticker, _name: asyncio.sleep(
                0, result=[{"title": "A", "link": "https://example.com/a"}]
            ),
        )
    )

    assert result.goto == "END"
    assert result.update["node_statuses"]["financial_news_research"] == "error"
    assert "artifact save failed" in result.update["error_logs"][0]["error"]
