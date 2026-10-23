import asyncio
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from pydantic import ValidationError

from src.agents.news.domain.search_strategy.contracts import SearchTask
from src.agents.news.domain.search_strategy.query_policy_service import (
    build_base_term,
    build_search_tasks,
    build_site_query,
)
from src.agents.news.domain.search_strategy.ranking_policy_service import (
    JITTER_SECONDS,
    MAX_CONCURRENT_REQUESTS,
    PRIORITY_ORDER,
    QUOTAS,
    SORT_TAG_PRIORITY,
    TIER_1_DOMAINS,
    TIER_2_DOMAINS,
    TOP_TIER_DOMAINS,
)
from src.search import NewsSearchRequest, SearchClientError, get_search_client
from src.shared.kernel.tools.logger import get_logger, log_event

logger = get_logger(__name__)

SearchResult = dict[str, object]
FormattedResult = dict[str, object]


async def _fetch_one_managed(
    task: SearchTask, semaphore: asyncio.Semaphore
) -> list[SearchResult]:
    """Search with the News slice's retry and query fallback policy."""
    import random
    import time

    async with semaphore:
        await asyncio.sleep(random.uniform(*JITTER_SECONDS))
        for query in (task.query,) + task.fallbacks:
            for attempt in range(2):
                started_at = time.perf_counter()
                try:
                    response = await get_search_client().search_news(
                        NewsSearchRequest(
                            query=query,
                            result_limit=task.limit,
                            time_range="week" if task.time_param == "w" else "month",
                        )
                    )
                    results: list[SearchResult] = [
                        {
                            "title": item.title,
                            "url": item.canonical_url,
                            "body": item.snippet,
                            "snippet": item.snippet,
                            "source": item.source or "",
                            "date": item.published_at.isoformat()
                            if item.published_at
                            else "",
                            "image": item.image_url or "",
                            "_time_frame": task.time_param,
                            "_search_tag": task.tag,
                        }
                        for item in response.results
                    ]
                    log_event(
                        logger,
                        event="news_search_query_completed",
                        message="news search query completed",
                        fields={
                            "tag": task.tag,
                            "timeframe": task.time_param,
                            "seconds": round(time.perf_counter() - started_at, 3),
                            "result_count": len(results),
                        },
                    )
                    if results:
                        return results
                    break
                except (SearchClientError, ValidationError) as exc:
                    retryable = (
                        exc.retryable if isinstance(exc, SearchClientError) else False
                    )
                    error_code = (
                        exc.code
                        if isinstance(exc, SearchClientError)
                        else "INVALID_REQUEST"
                    )
                    if not retryable or attempt == 1:
                        log_event(
                            logger,
                            event="news_search_query_failed",
                            message="news search query failed",
                            level=logging.WARNING,
                            error_code="NEWS_SEARCH_QUERY_FAILED",
                            fields={"tag": task.tag, "error_code": error_code},
                        )
                        break
                    await asyncio.sleep(1)
        return []


def _dedupe_results(
    results_lists: list[list[SearchResult]],
) -> tuple[dict[str, SearchResult], list[SearchResult]]:
    # --- Orthogonal Deduplication (Stacking Tags) ---
    # URL is the unique key, but Tags are a set (Orthogonal Tagging)
    unique_map: dict[str, SearchResult] = {}
    all_raw_results: list[SearchResult] = []
    for r_list in results_lists:
        all_raw_results.extend(r_list)

    for r in all_raw_results:
        link = r.get("url") or r.get("link")
        if not link:
            continue

        current_tag = r.get("_search_tag")

        if link not in unique_map:
            # First encounter: initialize category set
            r["_categories_set"] = {current_tag}
            unique_map[link] = r
        else:
            # Subsequent encounters: stack tags!
            unique_map[link]["_categories_set"].add(current_tag)

            # Keep the result with the LONGER snippet/content
            if len(r.get("body", "")) > len(unique_map[link].get("body", "")):
                unique_map[link]["body"] = r.get("body")
                unique_map[link]["title"] = r.get("title")

    return unique_map, all_raw_results


def _select_with_quotas(unique_map: dict[str, SearchResult]) -> list[SearchResult]:
    # --- Quota-based Selection (Bucket Filling) ---
    final_results: list[SearchResult] = []
    seen_urls: set[str] = set()
    all_items = list(unique_map.values())

    # Fill buckets in priority order to ensure ammo coverage
    for target_tag in PRIORITY_ORDER:
        quota = QUOTAS.get(target_tag, 2)
        count = 0
        for item in all_items:
            link = item.get("url")
            if link in seen_urls:
                continue

            # If this article hits the target intent
            if target_tag in item["_categories_set"]:
                final_results.append(item)
                seen_urls.add(link)
                count += 1

            if count >= quota:
                break

    # Fallback: fill up to 12-15 total results if some buckets are empty
    if len(final_results) < 10:
        for item in all_items:
            link = item.get("url")
            if link not in seen_urls:
                final_results.append(item)
                seen_urls.add(link)
                if len(final_results) >= 15:
                    break

    return final_results


def _format_results(final_results: list[SearchResult]) -> list[FormattedResult]:
    formatted_results: list[FormattedResult] = []
    for r in final_results:
        # Convert set to list for serialization
        cats = list(r.get("_categories_set", []))
        formatted_results.append(
            {
                "title": r.get("title", ""),
                "snippet": r.get("body", r.get("snippet", "")),
                "link": r.get("url", r.get("link", "")),
                "source": r.get("source", ""),
                "date": r.get("date", ""),
                "image": r.get("image", ""),
                "_time_frame": r.get("_time_frame", "m"),
                # Orthogonal categories (list) instead of mutually exclusive search_tag
                "categories": cats,
            }
        )
    return formatted_results


def _log_distribution(formatted_results: list[FormattedResult]) -> None:
    # Debug: Print final distribution
    final_counts: dict[str, int] = {}
    for r in formatted_results:
        cats = r.get("categories") or ["general"]
        for tag in cats:
            final_counts[tag] = final_counts.get(tag, 0) + 1
    log_event(
        logger,
        event="news_search_distribution",
        message="news search category distribution computed",
        fields={"counts": final_counts},
    )


def _extract_domain(link: str) -> str:
    try:
        netloc = urlparse(link).netloc
    except ValueError:
        return ""
    if not netloc:
        return ""
    return netloc.lower().removeprefix("www.")


def _domain_rank(link: str) -> int:
    domain = _extract_domain(link)
    if not domain:
        return 0
    if any(domain.endswith(d) for d in TOP_TIER_DOMAINS):
        return 3
    if any(domain.endswith(d) for d in TIER_1_DOMAINS):
        return 2
    if any(domain.endswith(d) for d in TIER_2_DOMAINS):
        return 1
    return 0


def _tag_rank(categories: list[str]) -> int:
    if not categories:
        return 0
    ranks = {tag: len(SORT_TAG_PRIORITY) - i for i, tag in enumerate(SORT_TAG_PRIORITY)}
    return max(ranks.get(tag, 0) for tag in categories)


def _parse_date(value: object) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    text = str(value).strip()
    if not text:
        return None

    try:
        iso = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass

    try:
        dt = parsedate_to_datetime(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        pass

    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%b %d, %Y",
        "%B %d, %Y",
        "%d %b %Y",
        "%d %B %Y",
    ):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return None


def _sort_results(formatted_results: list[FormattedResult]) -> list[FormattedResult]:
    def sort_key(item: FormattedResult) -> tuple[int, int, int, float]:
        date_value = _parse_date(item.get("date"))
        has_date = 1 if date_value else 0
        timestamp = date_value.timestamp() if date_value else 0.0
        link = str(item.get("link") or "")
        domain_score = _domain_rank(link)
        categories = item.get("categories") or []
        tag_score = _tag_rank(list(categories))
        return (has_date, domain_score, tag_score, timestamp)

    return sorted(formatted_results, key=sort_key, reverse=True)


async def news_search_multi_timeframe(
    ticker: str, company_name: str | None = None
) -> list[FormattedResult]:
    """
    Strategic parallel search with QUOTA-BASED diversity balancing.
    Now supports Company Name for better recall.
    """

    q_tier1 = build_site_query(TIER_1_DOMAINS)
    q_tier2 = build_site_query(TIER_2_DOMAINS)

    base_term = build_base_term(ticker, company_name)
    tasks_config = build_search_tasks(base_term, q_tier1, q_tier2)

    log_event(
        logger,
        event="news_search_multi_timeframe_started",
        message="news multi-timeframe search started",
        fields={"ticker": ticker, "company_name": company_name},
    )

    # === Rate Limit Protection ===
    # Limit concurrent requests to avoid triggering DDG's anti-scraping measures
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    # Execute with managed concurrency
    tasks = [_fetch_one_managed(task, semaphore) for task in tasks_config]
    results_lists = await asyncio.gather(*tasks)

    unique_map, all_raw_results = _dedupe_results(results_lists)
    final_results = _select_with_quotas(unique_map)
    formatted_results = _format_results(final_results)
    formatted_results = _sort_results(formatted_results)

    log_event(
        logger,
        event="news_search_multi_timeframe_completed",
        message="news multi-timeframe search completed",
        fields={
            "ticker": ticker,
            "raw_count": len(all_raw_results),
            "unique_count": len(unique_map),
            "balanced_count": len(formatted_results),
        },
    )

    _log_distribution(formatted_results)

    return formatted_results
