import asyncio
import logging
from dataclasses import dataclass, field

# Use the same logger setup as in the original __init__.py
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchTask:
    time_param: str
    query: str
    limit: int
    tag: str
    fallbacks: tuple[str, ...] = field(default_factory=tuple)


async def news_search_multi_timeframe(
    ticker: str, company_name: str = None
) -> list[dict]:
    """
    Strategic parallel search with QUOTA-BASED diversity balancing.
    Now supports Company Name for better recall.
    """

    # 1. Define Tiers (Domain Segregation)
    # Tier 1: Global Financial Core - Highest authority
    TIER_1_DOMAINS = [
        "bloomberg.com",
        "reuters.com",
        "wsj.com",
        "ft.com",
        "bbc.com",
    ]

    # Tier 2: Market & Depth Analysis - Supplementary insights
    TIER_2_DOMAINS = [
        "cnbc.com",
        "marketwatch.com",
        "barrons.com",
        "finance.yahoo.com",
        "nytimes.com",
        "fortune.com",
    ]

    def build_site_query(domains):
        return " OR ".join([f"site:{d}" for d in domains])

    q_tier1 = build_site_query(TIER_1_DOMAINS)
    q_tier2 = build_site_query(TIER_2_DOMAINS)

    # 1. Build Search Term (Precision vs Recall)
    # If company_name is provided, use (TICKER OR "Company Name")
    if company_name:
        base_term = f'({ticker} OR "{company_name}")'
    else:
        base_term = ticker

    def build_fallbacks(tag: str) -> tuple[str, ...]:
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

    # --- Strategic Search Task Configuration ---
    # Increased fetch counts to fill quota buckets
    tasks_config = [
        # [BULLISH_SIGNAL] Growth catalysts & Valuation (For Bull Agent)
        SearchTask(
            "m",
            f'{base_term} stock ("price target raised" OR "buy rating" OR upgrade OR outperform OR undervalued OR record OR partnership)',
            10,
            "bullish",
            build_fallbacks("bullish"),
        ),
        SearchTask(
            "m",
            f"{base_term} stock bullish news",
            10,
            "bullish",
            build_fallbacks("bullish"),
        ),
        # [BEARISH_SIGNAL] Risks, downgrades, & headwinds (For Bear Agent)
        SearchTask(
            "m",
            f'{base_term} stock (downgrade OR "sell rating" OR underperform OR overvalued OR "short seller" OR lawsuit OR investigation OR headwinds)',
            10,
            "bearish",
            build_fallbacks("bearish"),
        ),
        SearchTask(
            "m",
            f"{base_term} stock bearish news",
            10,
            "bearish",
            build_fallbacks("bearish"),
        ),
        # === [TRUSTED_NEWS] 拆分為 Tier 1 和 Tier 2 執行 ===
        # Avoids overly long queries while increasing coverage
        SearchTask(
            "w",
            f"{base_term} stock news ({q_tier1})",
            4,
            "trusted_news",
            build_fallbacks("trusted_news"),
        ),
        SearchTask(
            "m",
            f"{base_term} stock news ({q_tier1})",
            4,
            "trusted_news",
            build_fallbacks("trusted_news"),
        ),
        SearchTask(
            "w",
            f"{base_term} stock news ({q_tier2})",
            4,
            "trusted_news",
            build_fallbacks("trusted_news"),
        ),
        SearchTask(
            "m",
            f"{base_term} stock news ({q_tier2})",
            4,
            "trusted_news",
            build_fallbacks("trusted_news"),
        ),
        # [CORPORATE_EVENT] M&A, Capex, Management changes
        SearchTask(
            "w",
            f'{base_term} (merger OR acquisition OR investment OR "capital expenditure" OR CEO OR CFO)',
            10,
            "corporate_event",
            build_fallbacks("corporate_event"),
        ),
        SearchTask(
            "m",
            f'{base_term} (merger OR acquisition OR investment OR "capital expenditure" OR CEO OR CFO)',
            10,
            "corporate_event",
            build_fallbacks("corporate_event"),
        ),
        # [FINANCIALS] Earnings reports, SEC filings, Guidance
        SearchTask(
            "m",
            f'{base_term} earnings ("SEC filing" OR 10-K OR 10-Q OR guidance OR revenue)',
            10,
            "financials",
            build_fallbacks("financials"),
        ),
        # [ANALYST_OPINION] General analyst sentiment
        SearchTask(
            "w",
            f'{base_term} analyst rating "price target"',
            4,
            "analyst_opinion",
            build_fallbacks("analyst_opinion"),
        ),
        SearchTask(
            "m",
            f'{base_term} ("upcoming" OR "launch date" OR "roadmap" OR "revenue forecast" OR "outlook" OR "catalyst" OR "next quarter")',
            8,
            "financials",
            build_fallbacks("financials"),
        ),
    ]

    print(
        f"--- [Search] Starting diversified parallel search for {ticker} (Company: {company_name}) ---"
    )

    # === Rate Limit Protection ===
    # Limit concurrent requests to avoid triggering DDG's anti-scraping measures
    MAX_CONCURRENT_REQUESTS = 2
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    def _is_no_results_error(err: Exception) -> bool:
        return "No results found" in str(err)

    def _run_query(ddgs, query: str, time_param: str, limit: int) -> list[dict]:
        results = ddgs.news(
            query,
            region="wt-wt",
            safesearch="off",
            time=time_param,
            max_results=limit,
        )
        return list(results)

    def fetch_one_sync(task: SearchTask) -> list[dict]:
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
                        results_list = _run_query(
                            ddgs, query, task.time_param, task.limit
                        )
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

    async def fetch_one_managed(task: SearchTask):
        """Async wrapper with semaphore control and jitter."""
        import random

        async with semaphore:
            # Random jitter (0.5-2.0s) to avoid burst patterns
            await asyncio.sleep(random.uniform(3.0, 5.0))
            return await asyncio.to_thread(fetch_one_sync, task)

    # Execute with managed concurrency
    tasks = [fetch_one_managed(task) for task in tasks_config]
    results_lists = await asyncio.gather(*tasks)

    # --- Orthogonal Deduplication (Stacking Tags) ---
    # URL is the unique key, but Tags are a set (Orthogonal Tagging)
    unique_map = {}
    all_raw_results = []
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

    # --- Quota-based Selection (Bucket Filling) ---
    # Definition of priority order: fill specific debate ammunition first
    priority_order = [
        "corporate_event",
        "financials",
        "bullish",
        "bearish",
        "analyst_opinion",
        "trusted_news",
    ]

    # Target quotas for each bucket
    QUOTAS = {
        "corporate_event": 5,
        "financials": 2,
        "bullish": 5,
        "bearish": 5,
        "analyst_opinion": 2,
        "trusted_news": 4,
    }

    final_results = []
    seen_urls = set()
    all_items = list(unique_map.values())

    # Fill buckets in priority order to ensure ammo coverage
    for target_tag in priority_order:
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

    # --- Format output ---
    formatted_results = []
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

    logger.info(
        f"--- [Search] Combined: {len(all_raw_results)} -> Unique: {len(unique_map)} -> Balanced: {len(formatted_results)} ---"
    )

    # Debug: Print final distribution
    final_counts = {}
    for r in formatted_results:
        cats = r.get("categories") or ["general"]
        for tag in cats:
            final_counts[tag] = final_counts.get(tag, 0) + 1
    logger.info(f"--- [Search] Final Balanced Distribution: {final_counts} ---")

    return formatted_results
