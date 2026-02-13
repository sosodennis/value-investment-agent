import asyncio
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from src.agents.news.domain.policies import (
    JITTER_SECONDS,
    MAX_CONCURRENT_REQUESTS,
    PRIORITY_ORDER,
    QUOTAS,
    SORT_TAG_PRIORITY,
    TIER_1_DOMAINS,
    TIER_2_DOMAINS,
    TOP_TIER_DOMAINS,
    SearchTask,
    build_base_term,
    build_search_tasks,
    build_site_query,
)

# Use the same logger setup as in the original __init__.py
logger = logging.getLogger(__name__)

SearchResult = dict[str, object]
FormattedResult = dict[str, object]


def _is_no_results_error(err: Exception) -> bool:
    return "No results found" in str(err)


def _run_query(
    ddgs: object, query: str, time_param: str, limit: int
) -> list[SearchResult]:
    results = ddgs.news(
        query,
        region="wt-wt",
        safesearch="off",
        time=time_param,
        max_results=limit,
    )
    return list(results)


def _fetch_one_sync(task: SearchTask) -> list[SearchResult]:
    """Synchronous fetch with retry logic and fallbacks."""
    import time

    from ddgs import DDGS

    max_retries = 2
    queries = (task.query,) + task.fallbacks
    last_error: Exception | None = None

    for query in queries:
        for attempt in range(max_retries):
            try:
                if attempt == 0:
                    print(
                        f"--- [Search] Querying: {query[:60]}... ({task.time_param}) ---",
                        flush=True,
                    )

                with DDGS() as ddgs:
                    search_start = time.perf_counter()
                    results_list = _run_query(ddgs, query, task.time_param, task.limit)
                    search_end = time.perf_counter()

                    print(
                        f"--- [Search Latency] {search_end - search_start:.2f}s for query: {query[:50]}... ({task.time_param}) ---",
                        flush=True,
                    )

                    if not results_list:
                        break

                    for r in results_list:
                        r["_time_frame"] = task.time_param
                        r["_search_tag"] = task.tag
                    return results_list

            except Exception as e:
                if _is_no_results_error(e):
                    logger.info(
                        f"Search returned no results for tag='{task.tag}' query='{query[:80]}'"
                    )
                    break

                last_error = e
                if attempt == max_retries - 1:
                    break
                time.sleep(1)  # Brief pause before retry

    if last_error is not None:
        logger.warning(
            f"Search failed for tag='{task.tag}' after retries: {last_error}"
        )
    return []


async def _fetch_one_managed(
    task: SearchTask, semaphore: asyncio.Semaphore
) -> list[SearchResult]:
    """Async wrapper with semaphore control and jitter."""
    import random

    async with semaphore:
        # Random jitter (3.0-5.0s) to avoid burst patterns
        await asyncio.sleep(random.uniform(*JITTER_SECONDS))
        return await asyncio.to_thread(_fetch_one_sync, task)


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
    logger.info(f"--- [Search] Final Balanced Distribution: {final_counts} ---")


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

    print(
        f"--- [Search] Starting diversified parallel search for {ticker} (Company: {company_name}) ---"
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

    logger.info(
        f"--- [Search] Combined: {len(all_raw_results)} -> Unique: {len(unique_map)} -> Balanced: {len(formatted_results)} ---"
    )

    _log_distribution(formatted_results)

    return formatted_results
