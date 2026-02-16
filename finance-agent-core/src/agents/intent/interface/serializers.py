from __future__ import annotations

from collections.abc import Mapping

from src.agents.intent.domain.models import TickerCandidate
from src.agents.intent.interface.contracts import IntentExtraction
from src.agents.intent.interface.mappers import from_ticker_candidate
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
