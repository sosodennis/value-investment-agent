from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

from src.agents.news.domain.models import NewsAggregationResult
from src.agents.news.domain.services import (
    aggregate_news_items as domain_aggregate_news_items,
)
from src.agents.news.domain.services import (
    build_articles_to_fetch as domain_build_articles_to_fetch,
)
from src.agents.news.domain.services import (
    build_news_summary_message as domain_build_news_summary_message,
)
from src.agents.news.domain.services import (
    build_selector_fallback_indices as domain_build_selector_fallback_indices,
)
from src.agents.news.domain.services import (
    normalize_selected_indices as domain_normalize_selected_indices,
)
from src.common.tools.logger import get_logger
from src.common.types import AgentOutputArtifactPayload, JSONObject

logger = get_logger(__name__)


def aggregate_news_items(
    news_items: list[JSONObject], *, ticker: str
) -> NewsAggregationResult:
    return domain_aggregate_news_items(news_items, ticker=ticker)


def build_news_summary_message(*, ticker: str, result: NewsAggregationResult) -> str:
    return domain_build_news_summary_message(ticker=ticker, result=result)


def build_articles_to_fetch(
    raw_results: list[JSONObject], selected_indices: list[int]
) -> list[JSONObject]:
    return domain_build_articles_to_fetch(raw_results, selected_indices)


def build_selector_fallback_indices(raw_results: list[JSONObject]) -> list[int]:
    return domain_build_selector_fallback_indices(raw_results)


def normalize_selected_indices(
    selected_indices: list[int], *, limit: int = 10
) -> list[int]:
    return domain_normalize_selected_indices(selected_indices, limit=limit)


def build_cleaned_search_results(results: list[dict[str, object]]) -> list[JSONObject]:
    cleaned_results: list[JSONObject] = []
    for r in results:
        cleaned_results.append(
            {
                "title": r.get("title", ""),
                "source": r.get("source", ""),
                "snippet": r.get("snippet", ""),
                "link": r.get("link", ""),
                "date": r.get("date", ""),
                "categories": r.get("categories", [r.get("_search_tag", "general")]),
            }
        )
    return cleaned_results


def format_selector_input(cleaned_results: list[JSONObject]) -> str:
    formatted_list: list[str] = []
    for r in cleaned_results:
        categories = r.get("categories", [])
        categories_str = ", ".join([str(c).upper() for c in categories])
        formatted_list.append(
            f"""
Source: {r.get('source')} | [TAGS: {categories_str}] | Date: {r.get('date')}
Title: {r.get('title')}
Snippet: {r.get('snippet')}
URL: {r.get('link')}
--------------------------------------------------
"""
        )
    return "".join(formatted_list)


class _ChainLike(Protocol):
    def invoke(self, payload: object) -> object: ...


class _ModelDumpLike(Protocol):
    def model_dump(self, *, mode: str) -> JSONObject: ...


class _LLMLike(Protocol):
    def with_structured_output(self, schema: type[object]) -> object: ...


@dataclass(frozen=True)
class AnalysisChains:
    basic: _ChainLike
    finbert: _ChainLike


@dataclass(frozen=True)
class SelectorExecutionResult:
    selected_indices: list[int]
    is_degraded: bool
    error_message: str


@dataclass(frozen=True)
class FetchBuildResult:
    news_items: list[JSONObject]
    article_errors: list[str]


@dataclass(frozen=True)
class AnalystExecutionResult:
    news_items: list[JSONObject]
    article_errors: list[str]


class _FinbertResultLike(Protocol):
    label: str
    score: float
    has_numbers: bool

    def to_dict(self) -> JSONObject: ...


class _FinbertAnalyzerLike(Protocol):
    def is_available(self) -> bool: ...

    def analyze(self, content: str) -> _FinbertResultLike | None: ...


class _NewsArtifactPortLike(Protocol):
    async def save_news_article(
        self,
        *,
        data: JSONObject,
        produced_by: str,
        key_prefix: str,
    ) -> str | None: ...

    async def load_news_article_text(self, content_id: object) -> str | None: ...


def run_selector_with_fallback(
    *,
    chain: _ChainLike,
    ticker: str | None,
    formatted_results: str,
    raw_results: list[JSONObject],
) -> SelectorExecutionResult:
    try:
        response = chain.invoke({"ticker": ticker, "search_results": formatted_results})
        content = str(response.content)
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        selection_data = json.loads(content)
        selected_articles = selection_data.get("selected_articles")
        if selected_articles is None:
            return SelectorExecutionResult(
                selected_indices=build_selector_fallback_indices(raw_results),
                is_degraded=True,
                error_message="Selector returned no 'selected_articles' key.",
            )

        selected_urls = [
            article.get("url")
            for article in selected_articles
            if isinstance(article, dict) and article.get("url")
        ]
        url_to_idx = {
            result.get("link"): idx
            for idx, result in enumerate(raw_results)
            if result.get("link")
        }
        indices = [url_to_idx[url] for url in selected_urls if url in url_to_idx]
        return SelectorExecutionResult(
            selected_indices=normalize_selected_indices(indices),
            is_degraded=False,
            error_message="",
        )
    except Exception as exc:
        return SelectorExecutionResult(
            selected_indices=build_selector_fallback_indices(raw_results),
            is_degraded=True,
            error_message=str(exc),
        )


def parse_published_at(date_value: object) -> datetime | None:
    if not isinstance(date_value, str) or not date_value:
        return None
    try:
        return datetime.fromisoformat(date_value)
    except ValueError:
        return None


def build_news_item_payload(
    *,
    result: JSONObject,
    full_content: str | None,
    content_id: str | None,
    generated_id: str,
    reliability_score: float,
    item_factory: Callable[..., object],
    source_factory: Callable[..., object],
) -> JSONObject:
    url = str(result.get("link") or "")
    title = str(result.get("title") or "")
    source_name = (
        str(result.get("source"))
        if result.get("source")
        else (title.split(" - ")[-1] if " - " in title else "Unknown")
    )
    source_domain = url.split("//")[-1].split("/")[0] if url else "unknown"
    categories_raw = result.get("categories", [])
    categories = categories_raw if isinstance(categories_raw, list) else []

    item = item_factory(
        id=generated_id,
        url=url,
        title=title,
        snippet=str(result.get("snippet", "")),
        full_content=None,
        published_at=parse_published_at(result.get("date")),
        source=source_factory(
            name=source_name,
            domain=source_domain,
            reliability_score=reliability_score,
        ),
        categories=categories,
    )
    payload = item.model_dump(mode="json")
    payload["content_id"] = content_id
    payload["full_content"] = full_content
    return payload


def build_analysis_chain_payload(
    *,
    ticker: str,
    item: JSONObject,
    content_to_analyze: str,
    finbert_summary: JSONObject | None,
) -> JSONObject:
    source_raw = item.get("source")
    source_info = source_raw if isinstance(source_raw, dict) else {}
    base_payload: JSONObject = {
        "ticker": ticker,
        "title": str(item.get("title", "Unknown")),
        "source": str(source_info.get("name", "Unknown")),
        "published_at": "N/A",
        "content": content_to_analyze,
    }

    categories_raw = item.get("categories", ["general"])
    categories = categories_raw if isinstance(categories_raw, list) else ["general"]
    base_payload["search_tag"] = ", ".join([str(c).upper() for c in categories])

    if finbert_summary is not None:
        base_payload["finbert_sentiment"] = str(
            finbert_summary.get("label", "NEUTRAL")
        ).upper()
        base_payload["finbert_confidence"] = str(
            finbert_summary.get("confidence", "0.0%")
        )
        base_payload["finbert_has_numbers"] = (
            "Yes" if bool(finbert_summary.get("has_numbers")) else "No"
        )
    return base_payload


async def build_news_items_from_fetch_results(
    *,
    articles_to_fetch: list[JSONObject],
    full_contents: list[str | None],
    ticker: str | None,
    timestamp: int,
    port: _NewsArtifactPortLike,
    generate_news_id_fn: Callable[[str | None, str | None], str],
    get_source_reliability_fn: Callable[[str], float],
    item_factory: Callable[..., object],
    source_factory: Callable[..., object],
) -> FetchBuildResult:
    news_items: list[JSONObject] = []
    article_errors: list[str] = []

    ticker_value = ticker or "UNKNOWN"
    for idx, result in enumerate(articles_to_fetch):
        url = result.get("link")
        title = result.get("title")
        full_content = full_contents[idx] if idx < len(full_contents) else None

        content_id: str | None = None
        if full_content:
            try:
                content_id = await port.save_news_article(
                    data={"full_text": full_content, "title": title, "url": url},
                    produced_by="financial_news_research.fetch_node",
                    key_prefix=f"news_{ticker_value}_{timestamp}_{idx}",
                )
            except Exception as exc:
                logger.error("Failed to save artifact for %s: %s", url, exc)
                article_errors.append(f"Failed to save article content artifact: {exc}")

        try:
            item_dict = build_news_item_payload(
                result=result,
                full_content=full_content,
                content_id=content_id,
                generated_id=generate_news_id_fn(
                    url if isinstance(url, str) else None,
                    title if isinstance(title, str) else None,
                ),
                reliability_score=(
                    get_source_reliability_fn(url) if isinstance(url, str) else 0.5
                ),
                item_factory=item_factory,
                source_factory=source_factory,
            )
            news_items.append(item_dict)
        except Exception as exc:
            logger.error(
                "--- [News Research] ❌ Failed to create news item for URL %s: %s ---",
                url,
                exc,
            )
            article_errors.append(f"Failed to build canonical news item: {exc}")

    return FetchBuildResult(news_items=news_items, article_errors=article_errors)


def build_analysis_chains(
    *,
    llm: _LLMLike,
    prompt_basic: object,
    prompt_finbert: object,
    analysis_model_type: type[object],
) -> AnalysisChains:
    basic_structured = llm.with_structured_output(analysis_model_type)
    finbert_structured = llm.with_structured_output(analysis_model_type)
    basic_chain = cast(_ChainLike, prompt_basic | basic_structured)
    finbert_chain = cast(_ChainLike, prompt_finbert | finbert_structured)
    return AnalysisChains(basic=basic_chain, finbert=finbert_chain)


def run_analysis_with_fallback(
    *,
    chains: AnalysisChains,
    chain_payload: JSONObject,
    prefer_finbert_chain: bool,
) -> tuple[JSONObject, bool]:
    if prefer_finbert_chain:
        try:
            result = chains.finbert.invoke(chain_payload)
            model = cast(_ModelDumpLike, result)
            return model.model_dump(mode="json"), False
        except Exception:
            result = chains.basic.invoke(chain_payload)
            model = cast(_ModelDumpLike, result)
            return model.model_dump(mode="json"), True

    result = chains.basic.invoke(chain_payload)
    model = cast(_ModelDumpLike, result)
    return model.model_dump(mode="json"), False


async def analyze_news_items(
    *,
    news_items: list[JSONObject],
    ticker: str | None,
    port: _NewsArtifactPortLike,
    finbert_analyzer: _FinbertAnalyzerLike,
    chains: AnalysisChains,
) -> AnalystExecutionResult:
    article_errors: list[str] = []
    ticker_value = ticker or "UNKNOWN"

    for index, item in enumerate(news_items):
        try:
            content_to_analyze = str(item.get("snippet", ""))

            content_id = item.get("content_id")
            if content_id:
                try:
                    full_text = await port.load_news_article_text(content_id)
                    if isinstance(full_text, str):
                        content_to_analyze = full_text
                except Exception as exc:
                    logger.warning("Could not load full content for analysis: %s", exc)

            finbert_result: _FinbertResultLike | None = None
            finbert_summary: JSONObject | None = None
            if finbert_analyzer.is_available():
                finbert_result = await asyncio.to_thread(
                    finbert_analyzer.analyze, content_to_analyze
                )
                if finbert_result:
                    item["finbert_analysis"] = finbert_result.to_dict()
                    finbert_summary = {
                        "label": finbert_result.label,
                        "confidence": f"{finbert_result.score:.1%}",
                        "has_numbers": finbert_result.has_numbers,
                    }

            chain_payload = build_analysis_chain_payload(
                ticker=ticker_value,
                item=item,
                content_to_analyze=content_to_analyze,
                finbert_summary=finbert_summary,
            )
            analysis_payload, _used_fallback = run_analysis_with_fallback(
                chains=chains,
                chain_payload=chain_payload,
                prefer_finbert_chain=finbert_result is not None,
            )
            item["analysis"] = analysis_payload
            item["analysis"]["source"] = "llm"
        except Exception as exc:
            logger.error(
                "--- [News Research] ❌ Analysis FAILED for article %s: %s ---",
                index + 1,
                exc,
                exc_info=True,
            )
            article_errors.append(
                f"Analysis failed for {item.get('title', 'Unknown')}: {exc}"
            )

    return AnalystExecutionResult(news_items=news_items, article_errors=article_errors)


def build_fetch_node_update(
    *, news_items_id: str | None, article_errors: list[str]
) -> JSONObject:
    status = "degraded" if article_errors else "running"
    update: JSONObject = {
        "financial_news_research": {"news_items_artifact_id": news_items_id},
        "current_node": "fetch_node",
        "internal_progress": {"fetch_node": "done", "analyst_node": "running"},
        "node_statuses": {"financial_news_research": status},
    }
    if article_errors:
        update["error_logs"] = [
            {
                "node": "fetch_node",
                "error": article_errors[0],
                "severity": "warning",
            }
        ]
    return update


def build_analyst_node_update(
    *, news_items_id: str | None, article_errors: list[str]
) -> JSONObject:
    status = "degraded" if article_errors else "running"
    update: JSONObject = {
        "financial_news_research": {"news_items_artifact_id": news_items_id},
        "current_node": "analyst_node",
        "internal_progress": {"analyst_node": "done", "aggregator_node": "running"},
        "node_statuses": {"financial_news_research": status},
    }
    if article_errors:
        update["error_logs"] = [
            {
                "node": "analyst_node",
                "error": f"Failed to analyze {len(article_errors)} articles.",
                "severity": "warning",
            }
        ]
    return update


def build_search_node_no_ticker_update() -> JSONObject:
    return {
        "current_node": "search_node",
        "internal_progress": {"search_node": "done"},
    }


def build_search_node_error_update(error_message: str) -> JSONObject:
    return {
        "current_node": "search_node",
        "internal_progress": {"search_node": "error"},
        "node_statuses": {"financial_news_research": "error"},
        "error_logs": [
            {
                "node": "search_node",
                "error": f"Search failed: {error_message}",
                "severity": "error",
            }
        ],
    }


def build_search_node_empty_update() -> JSONObject:
    return {
        "news_items": [],
        "current_node": "search_node",
        "internal_progress": {"search_node": "done"},
    }


def build_search_node_success_update(
    *,
    artifact: AgentOutputArtifactPayload,
    article_count: int,
    search_artifact_id: str | None,
) -> JSONObject:
    return {
        "financial_news_research": {
            "artifact": artifact,
            "article_count": article_count,
            "search_artifact_id": search_artifact_id,
        },
        "current_node": "search_node",
        "internal_progress": {"search_node": "done", "selector_node": "running"},
        "node_statuses": {"financial_news_research": "running"},
    }


def build_selector_node_update(
    *,
    selection_artifact_id: str | None,
    is_degraded: bool,
    error_message: str,
) -> JSONObject:
    update: JSONObject = {
        "financial_news_research": {"selection_artifact_id": selection_artifact_id},
        "current_node": "selector_node",
        "internal_progress": {"selector_node": "done", "fetch_node": "running"},
    }
    if is_degraded:
        normalized_error = (
            error_message
            if "Selection failed" in error_message
            else f"Selection failed: {error_message}. Falling back to top articles."
            if error_message
            else "Selection failed due to an unknown error. Falling back to top articles."
        )
        update["node_statuses"] = {"financial_news_research": "degraded"}
        update["error_logs"] = [
            {
                "node": "selector_node",
                "error": normalized_error,
                "severity": "warning",
            }
        ]
    return update


def build_analyst_chain_error_update(error_message: str) -> JSONObject:
    return {
        "current_node": "analyst_node",
        "internal_progress": {"analyst_node": "error"},
        "node_statuses": {"financial_news_research": "error"},
        "error_logs": [
            {
                "node": "analyst_node",
                "error": f"Failed to create analysis chains: {error_message}",
                "severity": "error",
            }
        ],
    }
