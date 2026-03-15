from __future__ import annotations

from dataclasses import dataclass, field

from .timeframe import TimeframeCode

Scalar = float | int | str | bool | None


@dataclass(frozen=True)
class KeyLevel:
    price: float
    strength: float | None = None
    touches: int | None = None
    label: str | None = None


@dataclass(frozen=True)
class PatternFlag:
    name: str
    confidence: float | None = None
    notes: str | None = None


@dataclass(frozen=True)
class PatternFrame:
    support_levels: list[KeyLevel] = field(default_factory=list)
    resistance_levels: list[KeyLevel] = field(default_factory=list)
    breakouts: list[PatternFlag] = field(default_factory=list)
    trendlines: list[PatternFlag] = field(default_factory=list)
    pattern_flags: list[PatternFlag] = field(default_factory=list)
    confidence_scores: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class PatternPack:
    ticker: str
    as_of: str
    timeframes: dict[TimeframeCode, PatternFrame]
    pattern_summary: dict[str, Scalar] = field(default_factory=dict)
