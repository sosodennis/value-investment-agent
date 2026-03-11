from __future__ import annotations

from src.agents.intent.domain.ticker_candidate import TickerCandidate
from src.agents.intent.interface.contracts import TickerCandidateModel


def to_ticker_candidate(model: TickerCandidateModel) -> TickerCandidate:
    return TickerCandidate(
        symbol=model.symbol,
        name=model.name,
        exchange=model.exchange,
        type=model.type,
        confidence=model.confidence,
    )


def from_ticker_candidate(candidate: TickerCandidate) -> TickerCandidateModel:
    return TickerCandidateModel(
        symbol=candidate.symbol,
        name=candidate.name,
        exchange=candidate.exchange,
        type=candidate.type,
        confidence=candidate.confidence,
    )
