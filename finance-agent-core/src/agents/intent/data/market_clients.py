from __future__ import annotations

import logging
import os

import yfinance as yf
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper

from src.agents.intent.domain.models import TickerCandidate
from src.shared.cross_agent.domain.market_identity import CompanyProfile
from src.shared.kernel.tools.logger import get_logger, log_event

logger = get_logger(__name__)

DEFAULT_DDGS_REGION = os.getenv("DDGS_REGION", "us-en")
DEFAULT_DDGS_BACKEND = os.getenv("DDGS_BACKEND", "duckduckgo")


def get_company_profile(ticker: str) -> CompanyProfile | None:
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        if not info or "symbol" not in info:
            log_event(
                logger,
                event="intent_profile_not_found",
                message="company profile not found",
                level=logging.WARNING,
                error_code="INTENT_PROFILE_NOT_FOUND",
                fields={"ticker": ticker},
            )
            return None

        return CompanyProfile(
            ticker=ticker,
            name=info.get("longName") or info.get("shortName") or ticker,
            sector=info.get("sector"),
            industry=info.get("industry"),
            description=info.get("longBusinessSummary"),
            market_cap=info.get("marketCap"),
            is_profitable=None,
        )
    except Exception:
        return None


def search_ticker(query: str, limit: int = 5) -> list[TickerCandidate]:
    try:
        search = yf.Search(query)
        quotes = getattr(search, "quotes", [])

        candidates: list[TickerCandidate] = []
        for quote in quotes[:limit]:
            quote_type = quote.get("quoteType", "").upper()
            if quote_type not in ["EQUITY", "EQUITY_DEPRECATED"]:
                continue

            candidates.append(
                TickerCandidate(
                    symbol=quote.get("symbol"),
                    name=quote.get("longname")
                    or quote.get("shortname")
                    or quote.get("symbol"),
                    exchange=quote.get("exchDisp"),
                    type="stock",
                    confidence=1.0 if quote.get("symbol") == query.upper() else 0.9,
                )
            )

        if candidates:
            return candidates
    except Exception as exc:
        log_event(
            logger,
            event="intent_yfinance_search_failed",
            message="yfinance ticker search failed",
            level=logging.ERROR,
            error_code="INTENT_YFINANCE_SEARCH_FAILED",
            fields={"query": query, "exception": str(exc)},
        )

    return []


def web_search(query: str) -> str:
    try:
        if "ticker" in query.lower() or "stock" in query.lower():
            if "share class" not in query.lower():
                query += " share classes tickers"

        log_event(
            logger,
            event="intent_web_search_started",
            message="intent web search started",
            fields={"query": query},
        )

        search = DuckDuckGoSearchAPIWrapper(
            max_results=7,
            time="y",
            region=DEFAULT_DDGS_REGION,
            backend=DEFAULT_DDGS_BACKEND,
        )

        results = search.results(query, max_results=7)

        if not results:
            return "No search results found."

        formatted_output: list[str] = []
        for i, res in enumerate(results, 1):
            title = res.get("title", "No Title")
            snippet = res.get("snippet", "No Snippet")
            formatted_output.append(f"[{i}] Source: {title}\\nContent: {snippet}\\n")

        return "\\n---\\n".join(formatted_output)
    except Exception as exc:
        log_event(
            logger,
            event="intent_web_search_failed",
            message="intent web search failed",
            level=logging.ERROR,
            error_code="INTENT_WEB_SEARCH_FAILED",
            fields={"query": query, "exception": str(exc)},
        )
        return f"Web search currently unavailable. Error: {str(exc)}"
