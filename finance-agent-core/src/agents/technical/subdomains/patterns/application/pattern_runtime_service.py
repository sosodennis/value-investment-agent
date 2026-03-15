from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from src.agents.technical.domain.shared import (
    PatternFrame,
    PatternPack,
    PriceSeries,
    TimeframeCode,
)
from src.agents.technical.subdomains.patterns.domain import (
    build_pattern_summary,
    detect_pattern_frame,
)


@dataclass(frozen=True)
class PatternRuntimeRequest:
    ticker: str
    as_of: str
    series_by_timeframe: dict[TimeframeCode, PriceSeries]


@dataclass(frozen=True)
class PatternRuntimeResult:
    pattern_pack: PatternPack
    degraded_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PatternRuntimeService:
    timeframes: tuple[TimeframeCode, ...] = ("1d", "1wk")
    min_points: int = 60

    def compute(self, request: PatternRuntimeRequest) -> PatternRuntimeResult:
        frames: dict[TimeframeCode, PatternFrame] = {}
        degraded: list[str] = []

        for timeframe in self.timeframes:
            series = request.series_by_timeframe.get(timeframe)
            if series is None:
                degraded.append(f"{timeframe}_MISSING")
                frames[timeframe] = PatternFrame()
                continue

            price_series = _build_series(series.price_series)
            if len(price_series) < self.min_points:
                degraded.append(f"{timeframe}_INSUFFICIENT_POINTS")
                frames[timeframe] = PatternFrame()
                continue

            detection = detect_pattern_frame(price_series, timeframe=timeframe)
            frames[timeframe] = detection.frame
            degraded.extend(
                [f"{timeframe}_{reason}" for reason in detection.degraded_reasons]
            )

        pattern_pack = PatternPack(
            ticker=request.ticker,
            as_of=request.as_of,
            timeframes=frames,
            pattern_summary=build_pattern_summary(frames),
        )
        return PatternRuntimeResult(
            pattern_pack=pattern_pack, degraded_reasons=degraded
        )


def _build_series(raw_series: dict[str, float | int | None]) -> pd.Series:
    if not raw_series:
        return pd.Series(dtype=float)
    series = pd.Series(raw_series)
    try:
        series.index = pd.to_datetime(series.index)
    except Exception:
        pass
    series = series.sort_index()
    series = pd.to_numeric(series, errors="coerce")
    series = series.replace([math.inf, -math.inf], math.nan)
    return series.dropna()
