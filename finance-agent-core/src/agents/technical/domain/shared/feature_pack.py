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
class FeaturePack:
    ticker: str
    as_of: str
    timeframes: dict[TimeframeCode, FeatureFrame]
    feature_summary: dict[str, Scalar] = field(default_factory=dict)
