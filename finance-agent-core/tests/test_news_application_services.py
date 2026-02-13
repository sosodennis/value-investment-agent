from __future__ import annotations

import asyncio

from src.agents.news.application.services import (
    AnalysisChains,
    aggregate_news_items,
    analyze_news_items,
    build_analysis_chain_payload,
    build_analysis_chains,
    build_analyst_chain_error_update,
    build_analyst_node_update,
    build_articles_to_fetch,
    build_fetch_node_update,
    build_news_item_payload,
    build_news_items_from_fetch_results,
    build_news_summary_message,
    build_search_node_empty_update,
    build_search_node_error_update,
    build_search_node_no_ticker_update,
    build_search_node_success_update,
    build_selector_fallback_indices,
    build_selector_node_update,
    normalize_selected_indices,
    parse_published_at,
    run_analysis_with_fallback,
    run_selector_with_fallback,
)
from src.workflow.nodes.financial_news_research.structures import (
    FinancialNewsItem,
    SourceInfo,
)


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

    result = aggregate_news_items(news_items, ticker="GME")

    assert result.sentiment_label == "bullish"
    assert result.weighted_score > 0.3
    assert "Earnings beat" in result.key_themes
    assert result.report_payload["ticker"] == "GME"
    assert len(result.top_headlines) == 2


def test_build_news_summary_message_renders_expected_shape() -> None:
    result = aggregate_news_items([], ticker="GME")
    message = build_news_summary_message(ticker="GME", result=result)

    assert "### News Research: GME" in message
    assert "Overall Sentiment" in message
    assert "Themes:" in message


def test_build_articles_to_fetch_filters_out_of_range_indices() -> None:
    raw = [{"title": "A"}, {"title": "B"}]
    selected = build_articles_to_fetch(raw, [0, 2, 1])
    assert [item["title"] for item in selected] == ["A", "B"]


def test_build_news_item_payload_creates_canonical_item() -> None:
    payload = build_news_item_payload(
        result={
            "title": "Test - Reuters",
            "link": "https://example.com/x",
            "snippet": "snippet",
            "date": "2026-02-13T10:00:00",
            "categories": ["general"],
            "source": "Reuters",
        },
        full_content="full",
        content_id="artifact-x",
        generated_id="id-x",
        reliability_score=0.9,
        item_factory=FinancialNewsItem,
        source_factory=SourceInfo,
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

    search_error = build_search_node_error_update("boom")
    assert search_error["node_statuses"]["financial_news_research"] == "error"
    assert "Search failed" in search_error["error_logs"][0]["error"]

    empty = build_search_node_empty_update()
    assert empty["internal_progress"]["search_node"] == "done"

    success = build_search_node_success_update(
        artifact={
            "kind": "financial_news_research.output",
            "version": "v1",
            "summary": "ok",
            "preview": None,
            "reference": None,
        },
        article_count=3,
        search_artifact_id="a1",
    )
    assert success["financial_news_research"]["article_count"] == 3
    assert success["node_statuses"]["financial_news_research"] == "running"

    selector_degraded = build_selector_node_update(
        selection_artifact_id="s1",
        is_degraded=True,
        error_message="x",
    )
    assert selector_degraded["node_statuses"]["financial_news_research"] == "degraded"

    analyst_chain_error = build_analyst_chain_error_update("chain boom")
    assert analyst_chain_error["node_statuses"]["financial_news_research"] == "error"
    assert (
        "Failed to create analysis chains"
        in analyst_chain_error["error_logs"][0]["error"]
    )


def test_parse_published_at_invalid_returns_none() -> None:
    assert parse_published_at("bad-date") is None


def test_build_selector_fallback_indices_returns_top_three() -> None:
    raw_results = [{"t": "A"}, {"t": "B"}, {"t": "C"}, {"t": "D"}]
    assert build_selector_fallback_indices(raw_results) == [0, 1, 2]


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


def test_run_analysis_with_fallback_uses_basic_when_finbert_chain_fails() -> None:
    chains = AnalysisChains(
        basic=_GoodChain({"source_chain": "basic"}),
        finbert=_FailingChain(),
    )
    payload, used_fallback = run_analysis_with_fallback(
        chains=chains,
        chain_payload={"ticker": "GME"},
        prefer_finbert_chain=True,
    )
    assert used_fallback is True
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


def test_run_selector_with_fallback_parses_selected_urls() -> None:
    chain = _SelectorChain(
        '{"selected_articles":[{"url":"https://x.com/a"},{"url":"https://x.com/c"}]}'
    )
    result = run_selector_with_fallback(
        chain=chain,
        ticker="GME",
        formatted_results="...",
        raw_results=[
            {"link": "https://x.com/a"},
            {"link": "https://x.com/b"},
            {"link": "https://x.com/c"},
        ],
    )
    assert result.selected_indices == [0, 2]
    assert result.is_degraded is False


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
                {
                    "title": "News - Reuters",
                    "link": "https://x.com/a",
                    "snippet": "snippet",
                    "date": "2026-02-13T10:00:00",
                    "categories": ["general"],
                    "source": "Reuters",
                }
            ],
            full_contents=["full text"],
            ticker="GME",
            timestamp=123,
            port=_FakeNewsPort(),
            generate_news_id_fn=lambda _url, _title: "news-1",
            get_source_reliability_fn=lambda _url: 0.9,
            item_factory=FinancialNewsItem,
            source_factory=SourceInfo,
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
