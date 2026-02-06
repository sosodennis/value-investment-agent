import yfinance as yf

from src.common.tools.logger import get_logger

from ..structures import TickerCandidate

logger = get_logger(__name__)


def search_ticker(query: str, limit: int = 5) -> list[TickerCandidate]:
    """
    Search for ticker symbols using yfinance.Search.
    """
    try:
        search = yf.Search(query)
        quotes = getattr(search, "quotes", [])

        candidates = []
        for quote in quotes[:limit]:
            # Filter for stocks
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

    except Exception as e:
        logger.error(f"yfinance.Search failed: {e}")

    return []
