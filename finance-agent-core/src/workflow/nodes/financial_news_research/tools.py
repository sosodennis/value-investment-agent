import asyncio
import hashlib
import logging
from urllib.parse import urlparse

import trafilatura

logger = logging.getLogger(__name__)

# Reliability mapping for financial news sources
SOURCE_RELIABILITY_MAP = {
    "bloomberg.com": 1.0,
    "reuters.com": 1.0,
    "wsj.com": 1.0,
    "ft.com": 1.0,
    "sec.gov": 1.0,
    "cnbc.com": 0.8,
    "yahoo.com": 0.7,
    "finance.yahoo.com": 0.7,
    "marketwatch.com": 0.7,
    "barrons.com": 0.8,
    "investing.com": 0.6,
    "seekingalpha.com": 0.4,
    "reddit.com": 0.2,
    "twitter.com": 0.2,
    "x.com": 0.2,
}


async def news_search_multi_timeframe(ticker: str) -> list[dict]:
    """
    Strategic parallel search with QUOTA-BASED diversity balancing.

    Key Features:
    1. Specificity > Authority: More specific tags (financials, corporate_event)
       take priority over general tags (trusted_news) during deduplication.
    2. Quota System: Ensures balanced representation from each category.

    Search Strategy:
    - [TRUSTED_NEWS] High-trust sources (Reuters, Bloomberg, WSJ)
    - [CORPORATE_EVENT] M&A, Capex, Management changes
    - [FINANCIALS] Earnings, SEC filings
    - [ANALYST_OPINION] Analyst ratings (lower priority)
    """
    from collections import defaultdict

    # Build site: filter for high-trust domains
    trust_domains = ["reuters.com", "bloomberg.com", "wsj.com", "ft.com", "cnbc.com"]
    trust_query_part = " OR ".join([f"site:{d}" for d in trust_domains])

    # --- Strategic Search Task Configuration ---
    # Increased fetch counts to fill quota buckets
    tasks_config = [
        # [TRUSTED_NEWS] Weekly + Monthly for coverage
        ("w", f"{ticker} ({trust_query_part})", 6, "trusted_news"),
        ("m", f"{ticker} ({trust_query_part})", 6, "trusted_news"),
        # [CORPORATE_EVENT] M&A, Capex, Management changes
        (
            "w",
            f'{ticker} (merger OR acquisition OR investment OR "capital expenditure" OR CEO OR CFO)',
            6,
            "corporate_event",
        ),
        (
            "m",
            f'{ticker} (merger OR acquisition OR investment OR "capital expenditure" OR CEO OR CFO)',
            6,
            "corporate_event",
        ),
        # [FINANCIALS] Earnings reports, SEC filings
        ("m", f"{ticker} earnings SEC filing 10-K 10-Q guidance", 6, "financials"),
        # [BULLISH_SIGNAL] Growth catalysts (For Bull Agent)
        (
            "w",
            f'{ticker} ("price target raised" OR "buy rating" OR "outperform" OR growth OR record OR partnership)',
            4,
            "bullish",
        ),
        # [BEARISH_SIGNAL] Risks and downgrades (For Bear Agent)
        (
            "m",
            f'{ticker} (downgrade OR "sell rating" OR underperform OR "short seller" OR lawsuit OR investigation OR miss)',
            4,
            "bearish",
        ),
        # [ANALYST_OPINION] Analyst ratings - lower priority
        ("w", f'{ticker} analyst rating "price target"', 4, "analyst_opinion"),
    ]

    print(f"--- [Search] Starting diversified parallel search for {ticker} ---")

    def fetch_one_sync(time_param: str, query: str, limit: int, tag: str):
        from ddgs import DDGS

        try:
            with DDGS() as ddgs:
                results = ddgs.news(
                    query,
                    region="wt-wt",
                    safesearch="off",
                    time=time_param,
                    max_results=limit,
                )
                results_list = list(results)
                for r in results_list:
                    r["_time_frame"] = time_param
                    r["_search_tag"] = tag
                return results_list
        except Exception as e:
            logger.error(f"Search failed for tag='{tag}': {e}")
            return []

    # Run sync fetches in parallel using threads
    tasks = [
        asyncio.to_thread(fetch_one_sync, t, q, limit, tag)
        for t, q, limit, tag in tasks_config
    ]
    results_lists = await asyncio.gather(*tasks)

    # --- Specificity-based Deduplication ---
    # More specific tags win when same URL appears in multiple searches
    # This prevents "trusted_news" from cannibalizing event/financial news
    TAG_SPECIFICITY = {
        "financials": 4,  # Most specific (10-K, earnings)
        "corporate_event": 3,  # Very specific (M&A, CEO change)
        "bullish": 3.5,  # High interest for debate
        "bearish": 3.5,  # High interest for debate
        "trusted_news": 2,  # General authority
        "analyst_opinion": 1,  # General opinion
    }

    unique_map = {}
    all_raw_results = []
    for r_list in results_lists:
        all_raw_results.extend(r_list)

    for r in all_raw_results:
        link = r.get("url") or r.get("link")
        if not link:
            continue

        current_tag = r.get("_search_tag")
        new_priority = TAG_SPECIFICITY.get(current_tag, 0)

        if link not in unique_map:
            # Initialize with categorical tag set
            r["_categories_set"] = {current_tag}
            unique_map[link] = r
        else:
            # Merge categories! This ensures "Shared Reality" for Debate Agent
            unique_map[link]["_categories_set"].add(current_tag)

            # Keep the result with the HIGHER priority metadata if multiple found
            existing_tag = unique_map[link].get("_search_tag")
            existing_priority = TAG_SPECIFICITY.get(existing_tag, 0)

            if new_priority > existing_priority:
                # Update but keep the merged categories
                merged_categories = unique_map[link]["_categories_set"]
                unique_map[link] = r
                unique_map[link]["_categories_set"] = merged_categories

    # --- Quota-based Bucket Selection ---
    # Ensure diversity by allocating fixed slots per category
    buckets = defaultdict(list)
    for r in unique_map.values():
        tag = r.get("_search_tag", "general")
        buckets[tag].append(r)

    # Target quotas for balanced output (~12-14 articles total)
    QUOTAS = {
        "corporate_event": 5,  # Core: Events are most important for value investing
        "financials": 3,  # Core: Financial data and filings
        "bullish": 5,  # Debate ammo
        "bearish": 5,  # Debate ammo
        "trusted_news": 5,  # Base: General trusted news coverage
        "analyst_opinion": 2,  # Reference: Market sentiment
    }

    final_results = []

    # Fill buckets in priority order
    for tag in [
        "corporate_event",
        "financials",
        "bullish",
        "bearish",
        "trusted_news",
        "analyst_opinion",
    ]:
        quota = QUOTAS.get(tag, 2)
        available = buckets.get(tag, [])
        final_results.extend(available[:quota])

    # --- Format output ---
    formatted_results = []
    for r in final_results:
        # Convert set to list for serialization
        categories = list(r.get("_categories_set", {r.get("_search_tag", "general")}))
        formatted_results.append(
            {
                "title": r.get("title", ""),
                "snippet": r.get("body", r.get("snippet", "")),
                "link": r.get("url", r.get("link", "")),
                "source": r.get("source", ""),
                "date": r.get("date", ""),
                "image": r.get("image", ""),
                "_time_frame": r.get("_time_frame", "m"),
                "_search_tag": r.get("_search_tag", "general"),
                "categories": categories,
            }
        )

    print(
        f"--- [Search] Combined: {len(all_raw_results)} -> Unique: {len(unique_map)} -> Balanced: {len(formatted_results)} ---"
    )

    # Debug: Print final distribution
    final_counts = {}
    for r in formatted_results:
        tag = r.get("_search_tag", "general")
        final_counts[tag] = final_counts.get(tag, 0) + 1
    print(f"--- [Search] Final Balanced Distribution: {final_counts} ---")

    return formatted_results


# def news_search(ticker: str, max_results: int = 8) -> list[dict[str, str]]:
#     """
#     Existing sync news search (fallback).
#     """
#     try:
#         print(f"--- [Tool: news_search] Calling DDGS for: {ticker} ---")
#         results = []
#         with DDGS() as ddgs:
#             query = f"{ticker} stock news"
#             ddgs_gen = ddgs.news(
#                 query, safesearch="off", time="m", max_results=max_results
#             )
#             for r in ddgs_gen:
#                 results.append(
#                     {
#                         "title": r.get("title", ""),
#                         "snippet": r.get("body", ""),
#                         "link": r.get("url", ""),
#                         "source": r.get("source", ""),
#                         "date": r.get("date", ""),
#                         "image": r.get("image", ""),
#                     }
#                 )

#         print(f"--- [Tool: news_search] DDGS returned {len(results)} results ---")
#         return results
#     except Exception as e:
#         logger.error(f"News search failed: {e}")
#         return []


def generate_news_id(url: str, title: str = "") -> str:
    """
    Generate a unique hash ID for a news item based on its URL.
    """
    return hashlib.md5(url.encode()).hexdigest()


def get_source_reliability(url: str) -> float:
    """
    Calculate reliability score based on domain.
    """
    try:
        domain = urlparse(url).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]

        return SOURCE_RELIABILITY_MAP.get(domain, 0.5)
    except Exception:
        return 0.5


def fetch_clean_text(url: str, max_chars: int = 6000) -> str | None:
    """
    Fetch and clean article text using trafilatura (sync fallback).
    """
    try:
        print(f"--- [Tool: fetch_clean_text] Fetching URL: {url} ---")
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            logger.warning(f"Failed to fetch URL: {url}")
            return None

        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )

        if not text:
            logger.warning(f"Failed to extract text from URL: {url}")
            return None

        print(
            f"--- [Tool: fetch_clean_text] Successfully extracted {len(text)} chars from {url} ---"
        )
        return text[:max_chars]
    except Exception as e:
        logger.error(f"Error fetching/cleaning text from {url}: {e}")
        return None


async def fetch_clean_text_async(url: str, max_chars: int = 6000) -> str | None:
    """
    High-performance async fetch:
    1. httpx for true async non-blocking download (I/O bound)
    2. trafilatura for in-memory parsing (CPU bound but fast)
    """
    import httpx

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        # 1. Async download (true non-blocking)
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            print(f"--- [Fetch Async] 🚀 Requesting: {url} ---")
            resp = await client.get(url, headers=headers)

            if resp.status_code != 200:
                logger.warning(f"Failed to fetch {url}: Status {resp.status_code}")
                return None

            html_content = resp.text

        # 2. Sync parse (in-memory, CPU bound but typically < 50ms)
        text = trafilatura.extract(
            html_content,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )

        if not text:
            logger.warning(f"Failed to extract text from {url}")
            return None

        print(f"--- [Fetch Async] ✅ Extracted {len(text)} chars ---")
        return text[:max_chars]

    except httpx.RequestError as e:
        logger.error(f"Network error fetching {url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Parsing error for {url}: {e}")
        return None
