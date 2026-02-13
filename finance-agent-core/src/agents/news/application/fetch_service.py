from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from src.agents.news.application.ports import NewsArtifactArticleWriterPort
from src.agents.news.domain.services import (
    build_articles_to_fetch as domain_build_articles_to_fetch,
)
from src.common.tools.logger import get_logger
from src.common.types import JSONObject

logger = get_logger(__name__)


@dataclass(frozen=True)
class FetchBuildResult:
    news_items: list[JSONObject]
    article_errors: list[str]


def build_articles_to_fetch(
    raw_results: list[JSONObject], selected_indices: list[int]
) -> list[JSONObject]:
    return domain_build_articles_to_fetch(raw_results, selected_indices)


def build_cleaned_search_results(results: list[dict[str, object]]) -> list[JSONObject]:
    cleaned_results: list[JSONObject] = []
    for result in results:
        cleaned_results.append(
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
    return cleaned_results


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


async def build_news_items_from_fetch_results(
    *,
    articles_to_fetch: list[JSONObject],
    full_contents: list[str | None],
    ticker: str | None,
    timestamp: int,
    port: NewsArtifactArticleWriterPort,
    generate_news_id_fn: Callable[[str | None, str | None], str],
    get_source_reliability_fn: Callable[[str], float],
    item_factory: Callable[..., object],
    source_factory: Callable[..., object],
) -> FetchBuildResult:
    news_items: list[JSONObject] = []
    article_errors: list[str] = []

    ticker_value = ticker or "UNKNOWN"
    for index, result in enumerate(articles_to_fetch):
        url = result.get("link")
        title = result.get("title")
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
