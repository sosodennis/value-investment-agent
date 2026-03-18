from __future__ import annotations

from dataclasses import dataclass, field

from .indicator_snapshot import IndicatorSnapshot
from .timeframe import TimeframeCode

Scalar = float | int | str | bool | None


@dataclass(frozen=True)
class FeatureFrame:
    classic_indicators: dict[str, IndicatorSnapshot] = field(default_factory=dict)
    quant_features: dict[str, IndicatorSnapshot] = field(default_factory=dict)


@dataclass(frozen=True)
class FeatureSummary:
    classic_count: int = 0
    quant_count: int = 0
    timeframe_count: int = 0
    ready_timeframes: tuple[TimeframeCode, ...] = ()
    degraded_timeframes: tuple[TimeframeCode, ...] = ()
    regime_inputs_ready_timeframes: tuple[TimeframeCode, ...] = ()
    unavailable_indicator_count: int = 0
    overall_quality: str | None = None


@dataclass(frozen=True)
class FeaturePack:
    ticker: str
    as_of: str
    timeframes: dict[TimeframeCode, FeatureFrame]
    feature_summary: FeatureSummary = field(default_factory=FeatureSummary)
