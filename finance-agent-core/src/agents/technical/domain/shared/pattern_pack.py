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
class VolumeProfileSummary:
    poc: float | None = None
    vah: float | None = None
    val: float | None = None
    profile_method: str | None = None
    profile_fidelity: str | None = None
    bucket_count: int | None = None
    value_area_coverage: float | None = None


@dataclass(frozen=True)
class PatternFrame:
    support_levels: list[KeyLevel] = field(default_factory=list)
    resistance_levels: list[KeyLevel] = field(default_factory=list)
    volume_profile_levels: list[KeyLevel] = field(default_factory=list)
    volume_profile_summary: VolumeProfileSummary | None = None
    breakouts: list[PatternFlag] = field(default_factory=list)
    trendlines: list[PatternFlag] = field(default_factory=list)
    pattern_flags: list[PatternFlag] = field(default_factory=list)
    confluence_metadata: dict[str, Scalar] = field(default_factory=dict)
    confidence_scores: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class PatternPack:
    ticker: str
    as_of: str
    timeframes: dict[TimeframeCode, PatternFrame]
    pattern_summary: dict[str, Scalar] = field(default_factory=dict)
