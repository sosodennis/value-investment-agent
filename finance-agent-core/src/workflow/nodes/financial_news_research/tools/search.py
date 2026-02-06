import asyncio
import logging

# Use the same logger setup as in the original __init__.py
logger = logging.getLogger(__name__)


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

    # --- Strategic Search Task Configuration ---
    # Increased fetch counts to fill quota buckets
    tasks_config = [
        # [BULLISH_SIGNAL] Growth catalysts & Valuation (For Bull Agent)
        (
            "m",
            f'{base_term} stock ("price target raised" OR "buy rating" OR upgrade OR outperform OR undervalued OR record OR partnership)',
            10,
            "bullish",
        ),
        (
            "m",
            f"{base_term} stock bullish news",
            10,
            "bullish",
        ),
        # [BEARISH_SIGNAL] Risks, downgrades, & headwinds (For Bear Agent)
        (
            "m",
            f'{base_term} stock (downgrade OR "sell rating" OR underperform OR overvalued OR "short seller" OR lawsuit OR investigation OR headwinds)',
            10,
            "bearish",
        ),
        (
            "m",
            f"{base_term} stock bearish news",
            10,
            "bearish",
        ),
        # === [TRUSTED_NEWS] 拆分為 Tier 1 和 Tier 2 執行 ===
        # Avoids overly long queries while increasing coverage
        ("w", f"{base_term} stock news ({q_tier1})", 4, "trusted_news"),
        ("m", f"{base_term} stock news ({q_tier1})", 4, "trusted_news"),
        ("w", f"{base_term} stock news ({q_tier2})", 4, "trusted_news"),
        ("m", f"{base_term} stock news ({q_tier2})", 4, "trusted_news"),
        # [CORPORATE_EVENT] M&A, Capex, Management changes
        (
            "w",
            f'{base_term} (merger OR acquisition OR investment OR "capital expenditure" OR CEO OR CFO)',
            10,
            "corporate_event",
        ),
        (
            "m",
            f'{base_term} (merger OR acquisition OR investment OR "capital expenditure" OR CEO OR CFO)',
            10,
            "corporate_event",
        ),
        # [FINANCIALS] Earnings reports, SEC filings, Guidance
        (
            "m",
            f'{base_term} earnings ("SEC filing" OR 10-K OR 10-Q OR guidance OR revenue)',
            10,
            "financials",
        ),
        # [ANALYST_OPINION] General analyst sentiment
        ("w", f'{base_term} analyst rating "price target"', 4, "analyst_opinion"),
        (
            "m",
            f'{base_term} ("upcoming" OR "launch date" OR "roadmap" OR "revenue forecast" OR "outlook" OR "catalyst" OR "next quarter")',
            8,
            "financials",
        ),
    ]

    print(
        f"--- [Search] Starting diversified parallel search for {ticker} (Company: {company_name}) ---"
    )

    # === Rate Limit Protection ===
    # Limit concurrent requests to avoid triggering DDG's anti-scraping measures
    MAX_CONCURRENT_REQUESTS = 2
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    def fetch_one_sync(time_param: str, query: str, limit: int, tag: str):
        """Synchronous fetch with retry logic."""
        import time

        from ddgs import DDGS

        max_retries = 2
        for attempt in range(max_retries):
            try:
                if attempt == 0:
                    print(
                        f"--- [Search] Querying: {query[:60]}... ({time_param}) ---",
                        flush=True,
                    )

                with DDGS() as ddgs:
                    search_start = time.perf_counter()
                    results = ddgs.news(
                        query,
                        region="wt-wt",
                        safesearch="off",
                        time=time_param,
                        max_results=limit,
                    )
                    results_list = list(results)
                    search_end = time.perf_counter()

                    print(
                        f"--- [Search Latency] {search_end - search_start:.2f}s for query: {query[:50]}... ({time_param}) ---",
                        flush=True,
                    )

                    for r in results_list:
                        r["_time_frame"] = time_param
                        r["_search_tag"] = tag
                    return results_list

            except Exception as e:
                if attempt == max_retries - 1:
                    logger.warning(f"Search failed for tag='{tag}' after retries: {e}")
                else:
                    time.sleep(1)  # Brief pause before retry
        return []

    async def fetch_one_managed(time_param: str, query: str, limit: int, tag: str):
        """Async wrapper with semaphore control and jitter."""
        import random

        async with semaphore:
            # Random jitter (0.5-2.0s) to avoid burst patterns
            await asyncio.sleep(random.uniform(3.0, 5.0))
            return await asyncio.to_thread(
                fetch_one_sync, time_param, query, limit, tag
            )

    # Execute with managed concurrency
    tasks = [fetch_one_managed(t, q, limit, tag) for t, q, limit, tag in tasks_config]
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
        # Note: _search_tag might not exist in final formatted results, using categories[0] for debug print
        tag = r["categories"][0] if r.get("categories") else "general"
        final_counts[tag] = final_counts.get(tag, 0) + 1
    logger.info(f"--- [Search] Final Balanced Distribution: {final_counts} ---")

    return formatted_results
