from __future__ import annotations

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

MAX_CONCURRENT_REQUESTS = 4
JITTER_SECONDS: tuple[float, float] = (0.8, 1.8)
