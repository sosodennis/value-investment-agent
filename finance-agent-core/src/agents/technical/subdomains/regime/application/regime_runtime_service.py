from __future__ import annotations

from dataclasses import dataclass, field

from src.agents.technical.domain.shared import PriceSeries, TimeframeCode
from src.agents.technical.subdomains.regime.domain import (
    RegimeFrame,
    RegimePack,
    build_regime_summary,
    classify_regime_frame,
)


@dataclass(frozen=True)
class RegimeRuntimeRequest:
    ticker: str
    as_of: str
    series_by_timeframe: dict[TimeframeCode, PriceSeries]


@dataclass(frozen=True)
class RegimeRuntimeResult:
    regime_pack: RegimePack
    degraded_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RegimeRuntimeService:
    timeframes: tuple[TimeframeCode, ...] = ("1wk", "1d")

    def compute(self, request: RegimeRuntimeRequest) -> RegimeRuntimeResult:
        frames: dict[TimeframeCode, RegimeFrame] = {}
        degraded: list[str] = []

        for timeframe in self.timeframes:
            series = request.series_by_timeframe.get(timeframe)
            if series is None:
                degraded.append(f"{timeframe}_MISSING")
                continue
            result = classify_regime_frame(series, timeframe=timeframe)
            if result.frame is None:
                degraded.extend(
                    [f"{timeframe}_{reason}" for reason in result.degraded_reasons]
                )
                continue
            frames[timeframe] = result.frame
            degraded.extend(
                [f"{timeframe}_{reason}" for reason in result.degraded_reasons]
            )

        regime_pack = RegimePack(
            ticker=request.ticker,
            as_of=request.as_of,
            timeframes=frames,
            regime_summary=build_regime_summary(frames),
        )
        return RegimeRuntimeResult(regime_pack=regime_pack, degraded_reasons=degraded)
