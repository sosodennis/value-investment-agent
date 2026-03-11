from __future__ import annotations

import logging

import yfinance as yf

from src.agents.intent.domain.ticker_candidate import TickerCandidate
from src.shared.kernel.tools.logger import bounded_text, get_logger, log_event

logger = get_logger(__name__)


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
            fields={"query": query, "exception": bounded_text(exc)},
        )

    return []
