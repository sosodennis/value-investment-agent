from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

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
MAX_CONCURRENT_REQUESTS = 3
JITTER_SECONDS: tuple[float, float] = (3.0, 5.0)


@dataclass(frozen=True)
class SearchTask:
    time_param: str
    query: str
    limit: int
    tag: str
    fallbacks: tuple[str, ...] = field(default_factory=tuple)


def build_site_query(domains: Iterable[str]) -> str:
    return " OR ".join([f"site:{d}" for d in domains])


def build_base_term(ticker: str, company_name: str | None) -> str:
    if company_name:
        return f'({ticker} OR "{company_name}")'
    return ticker


def _build_fallbacks(base_term: str, tag: str) -> tuple[str, ...]:
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


def build_search_tasks(base_term: str, q_tier1: str, q_tier2: str) -> list[SearchTask]:
    return [
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
        SearchTask(
            "m",
            f'{base_term} earnings ("SEC filing" OR 10-K OR 10-Q OR guidance OR revenue)',
            10,
            "financials",
            _build_fallbacks(base_term, "financials"),
        ),
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
