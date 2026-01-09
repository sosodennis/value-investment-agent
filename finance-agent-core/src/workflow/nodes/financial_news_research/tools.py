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


async def news_search_multi_timeframe(
    ticker: str, max_results_total: int = 15
) -> list[dict]:
    """
    Parallel search across d, w, m timeframes with deduplication.
    Uses asyncio.to_thread to run sync DDGS calls in parallel.
    """

    # Config: (time_param, query_suffix, fetch_count)
    tasks_config = [
        ("d", f"{ticker} stock news", 5),  # Latest breaking
        ("w", f"{ticker} stock analysis", 5),  # Recent analysis
        ("m", f"{ticker} earnings and SEC filings", 5),  # Fundamentals
    ]

    print(f"--- [Search] Starting parallel search for {ticker} (d/w/m) ---")

    def fetch_one_sync(time_param, query, limit):
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
                # results is a generator/list? DDGS().news usually returns a generator.
                # Let's convert to list immediately in the thread.
                results_list = list(results)
                for r in results_list:
                    r["_time_frame"] = time_param
                return results_list
        except Exception as e:
            logger.error(f"Search failed for time='{time_param}': {e}")
            return []

    # Run sync fetches in parallel using threads
    tasks = [
        asyncio.to_thread(fetch_one_sync, t, q, limit) for t, q, limit in tasks_config
    ]
    results_lists = await asyncio.gather(*tasks)

    # --- Deduplication logic ---
    unique_map = {}
    all_raw_results = []
    for r_list in results_lists:
        all_raw_results.extend(r_list)

    # Order of importance for coverage: d > w > m
    # If same URL exists, keep the one from the shorter (more recent) timeframe
    for r in all_raw_results:
        link = r.get("url") or r.get("link")
        if not link:
            continue

        if link not in unique_map:
            unique_map[link] = r
        else:
            # Overwrite if current timeframe is 'd' or 'w' and existing is 'm'
            current_tf = r.get("_time_frame")
            existing_tf = unique_map[link].get("_time_frame")
            if current_tf == "d" or (current_tf == "w" and existing_tf == "m"):
                unique_map[link] = r

    final_results = []
    for r in unique_map.values():
        final_results.append(
            {
                "title": r.get("title", ""),
                "snippet": r.get("body", r.get("snippet", "")),
                "link": r.get("url", r.get("link", "")),
                "source": r.get("source", ""),
                "date": r.get("date", ""),
                "image": r.get("image", ""),
                "_time_frame": r.get("_time_frame", "m"),
            }
        )

    print(
        f"--- [Search] Combined: {len(all_raw_results)} -> Unique: {len(final_results)} ---"
    )
    return final_results


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


def fetch_clean_text(url: str, max_chars: int = 4000) -> str | None:
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


async def fetch_clean_text_async(url: str, max_chars: int = 4000) -> str | None:
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
