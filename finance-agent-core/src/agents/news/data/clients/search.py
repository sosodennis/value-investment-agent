import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

# Use the same logger setup as in the original __init__.py
logger = logging.getLogger(__name__)

SearchResult = dict[str, object]
FormattedResult = dict[str, object]

# Domain tiers
TOP_TIER_DOMAINS = (
    "bloomberg.com",
    "reuters.com",
    "wsj.com",
)
TIER_1_DOMAINS = (
    "bloomberg.com",
    "reuters.com",
    "wsj.com",
    "ft.com",
    "bbc.com",
)
TIER_2_DOMAINS = (
    "cnbc.com",
    "marketwatch.com",
    "barrons.com",
    "finance.yahoo.com",
    "nytimes.com",
    "fortune.com",
)

# Selection priorities and quotas
PRIORITY_ORDER = (
    "corporate_event",
    "financials",
    "bullish",
    "bearish",
    "analyst_opinion",
    "trusted_news",
)
SORT_TAG_PRIORITY = (
    "corporate_event",
    "financials",
    "bearish",
    "bullish",
    "analyst_opinion",
    "trusted_news",
)
QUOTAS: dict[str, int] = {
    "corporate_event": 5,
    "financials": 2,
    "bullish": 5,
    "bearish": 5,
    "analyst_opinion": 2,
    "trusted_news": 4,
}

MAX_CONCURRENT_REQUESTS = 2
JITTER_SECONDS = (3.0, 5.0)


@dataclass(frozen=True)
class SearchTask:
    time_param: str
    query: str
    limit: int
    tag: str
    fallbacks: tuple[str, ...] = field(default_factory=tuple)


def _build_site_query(domains: Iterable[str]) -> str:
    return " OR ".join([f"site:{d}" for d in domains])


def _build_base_term(ticker: str, company_name: str | None) -> str:
    if company_name:
        return f'({ticker} OR "{company_name}")'
    return ticker


def _build_fallbacks(base_term: str, tag: str) -> tuple[str, ...]:
    # Keep fallbacks simple and broader to avoid zero-result hard failures.
    if tag in ("bullish", "bearish"):
        return (f"{base_term} stock news", f"{base_term} stock")
    if tag == "corporate_event":
        return (
            f"{base_term} (merger OR acquisition OR investment OR CEO OR CFO)",
            f"{base_term} news",
        )
    if tag == "financials":
        return (f"{base_term} earnings", f"{base_term} 10-K 10-Q")
    if tag == "trusted_news":
        return (f"{base_term} stock news",)
    if tag == "analyst_opinion":
        return (f"{base_term} analyst rating",)
    return ()


def _build_tasks(base_term: str, q_tier1: str, q_tier2: str) -> list[SearchTask]:
    # --- Strategic Search Task Configuration ---
    # Increased fetch counts to fill quota buckets
    return [
        # [BULLISH_SIGNAL] Growth catalysts & Valuation (For Bull Agent)
        SearchTask(
            "m",
            f'{base_term} stock ("price target raised" OR "buy rating" OR upgrade OR outperform OR undervalued OR record OR partnership)',
            10,
            "bullish",
            _build_fallbacks(base_term, "bullish"),
        ),
        SearchTask(
            "m",
            f"{base_term} stock bullish news",
            10,
            "bullish",
            _build_fallbacks(base_term, "bullish"),
        ),
        # [BEARISH_SIGNAL] Risks, downgrades, & headwinds (For Bear Agent)
        SearchTask(
            "m",
            f'{base_term} stock (downgrade OR "sell rating" OR underperform OR overvalued OR "short seller" OR lawsuit OR investigation OR headwinds)',
            10,
            "bearish",
            _build_fallbacks(base_term, "bearish"),
        ),
        SearchTask(
            "m",
            f"{base_term} stock bearish news",
            10,
            "bearish",
            _build_fallbacks(base_term, "bearish"),
        ),
        # === [TRUSTED_NEWS] 拆分為 Tier 1 和 Tier 2 執行 ===
        # Avoids overly long queries while increasing coverage
        SearchTask(
            "w",
            f"{base_term} stock news ({q_tier1})",
            4,
            "trusted_news",
            _build_fallbacks(base_term, "trusted_news"),
        ),
        SearchTask(
            "m",
            f"{base_term} stock news ({q_tier1})",
            4,
            "trusted_news",
            _build_fallbacks(base_term, "trusted_news"),
        ),
        SearchTask(
            "w",
            f"{base_term} stock news ({q_tier2})",
            4,
            "trusted_news",
            _build_fallbacks(base_term, "trusted_news"),
        ),
        SearchTask(
            "m",
            f"{base_term} stock news ({q_tier2})",
            4,
            "trusted_news",
            _build_fallbacks(base_term, "trusted_news"),
        ),
        # [CORPORATE_EVENT] M&A, Capex, Management changes
        SearchTask(
            "w",
            f'{base_term} (merger OR acquisition OR investment OR "capital expenditure" OR CEO OR CFO)',
            10,
            "corporate_event",
            _build_fallbacks(base_term, "corporate_event"),
        ),
        SearchTask(
            "m",
            f'{base_term} (merger OR acquisition OR investment OR "capital expenditure" OR CEO OR CFO)',
            10,
            "corporate_event",
            _build_fallbacks(base_term, "corporate_event"),
        ),
        # [FINANCIALS] Earnings reports, SEC filings, Guidance
        SearchTask(
            "m",
            f'{base_term} earnings ("SEC filing" OR 10-K OR 10-Q OR guidance OR revenue)',
            10,
            "financials",
            _build_fallbacks(base_term, "financials"),
        ),
        # [ANALYST_OPINION] General analyst sentiment
        SearchTask(
            "w",
            f'{base_term} analyst rating "price target"',
            4,
            "analyst_opinion",
            _build_fallbacks(base_term, "analyst_opinion"),
        ),
        SearchTask(
            "m",
            f'{base_term} ("upcoming" OR "launch date" OR "roadmap" OR "revenue forecast" OR "outlook" OR "catalyst" OR "next quarter")',
            8,
            "financials",
            _build_fallbacks(base_term, "financials"),
        ),
    ]


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

    q_tier1 = _build_site_query(TIER_1_DOMAINS)
    q_tier2 = _build_site_query(TIER_2_DOMAINS)

    base_term = _build_base_term(ticker, company_name)
    tasks_config = _build_tasks(base_term, q_tier1, q_tier2)

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
