from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from src.agents.news.application.ports import (
    NewsArtifactArticleWriterPort,
    NewsItemFactoryLike,
    SourceFactoryLike,
)
from src.agents.news.interface.contracts import NewsSearchResultItemModel
from src.agents.news.interface.parsers import parse_news_search_result_items
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject

logger = get_logger(__name__)


@dataclass(frozen=True)
class FetchBuildResult:
    news_items: list[JSONObject]
    article_errors: list[str]


def build_articles_to_fetch(
    raw_results: list[NewsSearchResultItemModel], selected_indices: list[int]
) -> list[NewsSearchResultItemModel]:
    selected: list[NewsSearchResultItemModel] = []
    for idx in selected_indices:
        if idx >= len(raw_results):
            continue
        selected.append(raw_results[idx])
    return selected


def build_cleaned_search_results(results: list[dict[str, object]]) -> list[JSONObject]:
    candidates: list[JSONObject] = []
    for result in results:
        candidates.append(
            {
                "title": result.get("title", ""),
                "source": result.get("source", ""),
                "snippet": result.get("snippet", ""),
                "link": result.get("link", ""),
                "date": result.get("date", ""),
                "categories": result.get(
                    "categories", [result.get("_search_tag", "general")]
                ),
            }
        )
    parsed = parse_news_search_result_items(
        candidates,
        context="news search results",
    )
    return [item.model_dump(mode="json") for item in parsed]


def parse_published_at(date_value: object) -> datetime | None:
    if not isinstance(date_value, str) or not date_value:
        return None
    try:
        return datetime.fromisoformat(date_value)
    except ValueError:
        return None


def build_news_item_payload(
    *,
    result: NewsSearchResultItemModel,
    full_content: str | None,
    content_id: str | None,
    generated_id: str,
    reliability_score: float,
    item_factory: NewsItemFactoryLike,
    source_factory: SourceFactoryLike,
) -> JSONObject:
    url = result.link
    title = result.title
    source_name = result.source or (
        title.split(" - ")[-1] if " - " in title else "Unknown"
    )
    source_domain = url.split("//")[-1].split("/")[0] if url else "unknown"
    categories = [item for item in result.categories if item]

    item = item_factory(
        id=generated_id,
        url=url,
        title=title,
        snippet=result.snippet,
        full_content=None,
        published_at=parse_published_at(result.date),
        source=source_factory(
            name=source_name,
            domain=source_domain,
            reliability_score=reliability_score,
        ),
        categories=categories,
    )
    payload = item.model_dump(mode="json")
    if not isinstance(payload, dict):
        raise TypeError("news item factory output must serialize to JSON object")
    payload["content_id"] = content_id
    payload["full_content"] = full_content
    return payload


async def build_news_items_from_fetch_results(
    *,
    articles_to_fetch: list[NewsSearchResultItemModel],
    full_contents: list[str | None],
    ticker: str | None,
    timestamp: int,
    port: NewsArtifactArticleWriterPort,
    generate_news_id_fn: Callable[[str | None, str | None], str],
    get_source_reliability_fn: Callable[[str], float],
    item_factory: NewsItemFactoryLike,
    source_factory: SourceFactoryLike,
) -> FetchBuildResult:
    news_items: list[JSONObject] = []
    article_errors: list[str] = []

    ticker_value = ticker or "UNKNOWN"
    for index, result in enumerate(articles_to_fetch):
        url = result.link
        title = result.title
        full_content = full_contents[index] if index < len(full_contents) else None

        content_id: str | None = None
        if full_content:
            try:
                content_id = await port.save_news_article(
                    data={"full_text": full_content, "title": title, "url": url},
                    produced_by="financial_news_research.fetch_node",
                    key_prefix=f"news_{ticker_value}_{timestamp}_{index}",
                )
            except Exception as exc:
                log_event(
                    logger,
                    event="news_fetch_article_artifact_save_failed",
                    message="failed to save news article text artifact",
                    level=logging.ERROR,
                    error_code="NEWS_ARTICLE_ARTIFACT_SAVE_FAILED",
                    fields={"url": url, "ticker": ticker_value, "exception": str(exc)},
                )
                article_errors.append(f"Failed to save article content artifact: {exc}")

        try:
            item_dict = build_news_item_payload(
                result=result,
                full_content=full_content,
                content_id=content_id,
                generated_id=generate_news_id_fn(url, title),
                reliability_score=get_source_reliability_fn(url) if url else 0.5,
                item_factory=item_factory,
                source_factory=source_factory,
            )
            news_items.append(item_dict)
        except Exception as exc:
            log_event(
                logger,
                event="news_fetch_item_build_failed",
                message="failed to build canonical news item",
                level=logging.ERROR,
                error_code="NEWS_ITEM_BUILD_FAILED",
                fields={"url": url, "ticker": ticker_value, "exception": str(exc)},
            )
            article_errors.append(f"Failed to build canonical news item: {exc}")

    return FetchBuildResult(news_items=news_items, article_errors=article_errors)
