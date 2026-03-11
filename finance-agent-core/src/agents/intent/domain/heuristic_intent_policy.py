from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class HeuristicIntent:
    company_name: str | None
    ticker: str | None
    is_valuation_request: bool
    reasoning: str


def heuristic_extract_intent(query: str) -> HeuristicIntent:
    query_lower = query.lower()

    tickers = re.findall(r"\b[A-Z]{1,5}\b", query)
    ticker = tickers[0] if tickers else None

    company_name = ticker
    if not company_name:
        stop_words = {
            "valuation",
            "valuate",
            "value",
            "price",
            "stock",
            "analysis",
            "report",
            "for",
            "of",
            "the",
            "a",
            "an",
        }
        words = query.split()
        potential_names = [
            w for w in words if w.lower() not in stop_words and len(w) > 1
        ]
        if potential_names:
            company_name = potential_names[-1]
        elif words:
            company_name = words[-1]

    return HeuristicIntent(
        company_name=company_name,
        ticker=ticker,
        is_valuation_request="val" in query_lower
        or "price" in query_lower
        or ticker is not None,
        reasoning="Fallback heuristic used due to API error.",
    )
