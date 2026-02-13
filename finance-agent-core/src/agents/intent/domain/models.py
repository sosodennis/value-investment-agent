from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TickerCandidate:
    """Domain value object for a candidate ticker."""

    symbol: str
    name: str
    exchange: str | None = None
    type: str | None = None
    confidence: float = 1.0
