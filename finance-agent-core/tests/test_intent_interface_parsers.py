from __future__ import annotations

from src.agents.intent.interface.parsers import (
    parse_resume_selection_input,
    parse_ticker_candidates,
)


def test_parse_ticker_candidates_filters_and_parses() -> None:
    raw = [
        {
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "exchange": "NASDAQ",
            "type": "stock",
            "confidence": 0.95,
        },
        "invalid",
        {"symbol": "MSFT", "name": "Microsoft", "confidence": 0.9},
    ]

    parsed = parse_ticker_candidates(raw)

    assert len(parsed) == 2
    assert parsed[0].symbol == "AAPL"
    assert parsed[0].confidence == 0.95
    assert parsed[1].symbol == "MSFT"


def test_parse_resume_selection_input_handles_selected_symbol_only() -> None:
    parsed_selected = parse_resume_selection_input({"selected_symbol": "  TSLA  "})
    assert parsed_selected.selected_symbol == "TSLA"

    parsed_legacy_ticker = parse_resume_selection_input({"ticker": "  NVDA  "})
    assert parsed_legacy_ticker.selected_symbol is None

    parsed_empty = parse_resume_selection_input({"selected_symbol": "   "})
    assert parsed_empty.selected_symbol is None
