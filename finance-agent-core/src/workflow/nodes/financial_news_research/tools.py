"""
Utility tools for Financial News Research.
"""

import hashlib
import logging
from urllib.parse import urlparse

import trafilatura
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper

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


def news_search(ticker: str, max_results: int = 8) -> list[dict[str, str]]:
    """
    Search for news using DuckDuckGo and return structured results.
    """
    try:
        query = f"recent news and developments for {ticker} stock"
        # Use 'y' for past year, but we want very recent, maybe 'm' for month or 'w' for week?
        # User specified "recent news". Let's use 'w' for week if we want high relevance.
        # Actually 'm' is safer for less frequent news.
        print(f"--- [Tool: news_search] Calling DuckDuckGo for: {query} ---")
        search = DuckDuckGoSearchAPIWrapper(max_results=max_results, time="m")
        results = search.results(query, max_results=max_results)
        print(
            f"--- [Tool: news_search] DuckDuckGo returned {len(results or [])} results ---"
        )
        return results
    except Exception as e:
        logger.error(f"News search failed: {e}")
        return []


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
    Fetch and clean article text using trafilatura.
    """
    try:
        print(f"--- [Tool: fetch_clean_text] Fetching URL: {url} ---")
        # trafilatura.fetch_url doesn't have a direct timeout param in some versions,
        # but we can wrap it if needed. For now, let's at least log.
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            logger.warning(f"Failed to fetch URL: {url}")
            return None

        # Extract core content, excluding comments and tables to save tokens
        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )

        if not text:
            logger.warning(f"Failed to extract text from URL: {url}")
            return None

        # Truncate to stay within token limits
        print(
            f"--- [Tool: fetch_clean_text] Successfully extracted {len(text)} chars from {url} ---"
        )
        return text[:max_chars]
    except Exception as e:
        logger.error(f"Error fetching/cleaning text from {url}: {e}")
        return None
