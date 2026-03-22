from __future__ import annotations

from collections.abc import Mapping

from src.agents.intent.domain.ticker_candidate import TickerCandidate
from src.agents.intent.interface.contracts import IntentExtraction
from src.agents.intent.interface.ticker_candidate_mapper import from_ticker_candidate
from src.shared.kernel.types import JSONObject


def serialize_ticker_candidates(candidates: list[TickerCandidate]) -> list[JSONObject]:
    return [
        from_ticker_candidate(candidate).model_dump(mode="json")
        for candidate in candidates
    ]


def serialize_ticker_selection_interrupt_payload(
    *,
    candidates: list[TickerCandidate],
    extracted_intent: object,
    reason: str = "Multiple tickers found or ambiguity detected.",
) -> JSONObject:
    intent_payload: JSONObject | None = None
    if isinstance(extracted_intent, Mapping):
        intent_payload = IntentExtraction.model_validate(extracted_intent).model_dump(
            mode="json"
        )

    return {
        "type": "ticker_selection",
        "candidates": serialize_ticker_candidates(candidates),
        "intent": intent_payload,
        "reason": reason,
    }


def build_ticker_selection_interrupt_ui_payload(
    *,
    candidates: list[TickerCandidate],
    reason: str = "Multiple tickers found or ambiguity detected.",
) -> JSONObject:
    ticker_options = [candidate.symbol for candidate in candidates]
    ticker_titles = [
        f"{candidate.symbol} - {candidate.name} ({(candidate.confidence * 100):.0f}% match)"
        for candidate in candidates
    ]

    return {
        "type": "ticker_selection",
        "title": "Ticker Resolution",
        "description": reason,
        "data": {},
        "schema": {
            "title": "Select Correct Ticker",
            "type": "object",
            "properties": {
                "selected_symbol": {
                    "type": "string",
                    "title": "Target Company",
                    "enum": ticker_options,
                    "oneOf": [
                        {"const": symbol, "title": ticker_titles[idx]}
                        for idx, symbol in enumerate(ticker_options)
                    ],
                }
            },
            "required": ["selected_symbol"],
        },
        "ui_schema": {"selected_symbol": {"ui:widget": "radio"}},
    }
