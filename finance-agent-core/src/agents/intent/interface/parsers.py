from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from src.agents.intent.domain.models import TickerCandidate
from src.agents.intent.interface.contracts import TickerCandidateModel
from src.agents.intent.interface.mappers import to_ticker_candidate


def parse_ticker_candidates(value: object) -> list[TickerCandidate]:
    if not isinstance(value, list):
        return []
    parsed: list[TickerCandidate] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            continue
        parsed.append(to_ticker_candidate(TickerCandidateModel.model_validate(raw)))
    return parsed


@dataclass(frozen=True)
class ResolvedSelectionInput:
    selected_symbol: str | None
    ticker: str | None


def parse_resume_selection_input(value: object) -> ResolvedSelectionInput:
    if not isinstance(value, Mapping):
        return ResolvedSelectionInput(selected_symbol=None, ticker=None)
    selected_symbol_raw = value.get("selected_symbol")
    selected_symbol = (
        selected_symbol_raw.strip()
        if isinstance(selected_symbol_raw, str) and selected_symbol_raw.strip()
        else None
    )
    ticker_raw = value.get("ticker")
    ticker = (
        ticker_raw.strip()
        if isinstance(ticker_raw, str) and ticker_raw.strip()
        else None
    )
    return ResolvedSelectionInput(selected_symbol=selected_symbol, ticker=ticker)
