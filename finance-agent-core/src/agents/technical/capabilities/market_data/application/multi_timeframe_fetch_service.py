from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.agents.technical.domain.shared.timeframe import TimeframeCode

from .ports import (
    IMarketDataProvider,
    MarketDataCacheMetadata,
    MarketDataProviderFailure,
    MarketDataTimeseriesBundleResult,
)

_INTERVAL_MAP: dict[TimeframeCode, str] = {
    "1d": "1d",
    "1wk": "1wk",
    "1h": "1h",
}


@dataclass(frozen=True)
class MultiTimeframeFetchRequest:
    ticker: str
    timeframes: list[TimeframeCode]
    period: str = "5y"


def fetch_timeseries_bundle(
    provider: IMarketDataProvider,
    request: MultiTimeframeFetchRequest,
) -> MarketDataTimeseriesBundleResult:
    frames: dict[TimeframeCode, pd.DataFrame] = {}
    failures: dict[TimeframeCode, MarketDataProviderFailure] = {}
    degraded_reasons: list[str] = []
    cache_meta: dict[TimeframeCode, MarketDataCacheMetadata] = {}

    for timeframe in request.timeframes:
        interval = _INTERVAL_MAP.get(timeframe, "1d")
        result = provider.fetch_ohlcv(
            request.ticker,
            period=request.period,
            interval=interval,
        )
        if result.failure is not None or result.data is None or result.data.empty:
            failures[timeframe] = result.failure or MarketDataProviderFailure(
                failure_code="MARKET_DATA_EMPTY",
                reason="empty_payload",
            )
            degraded_reasons.append(f"{timeframe}_UNAVAILABLE")
            continue
        frames[timeframe] = result.data
        if result.cache is not None:
            cache_meta[timeframe] = result.cache

    return MarketDataTimeseriesBundleResult(
        frames=frames,
        degraded_reasons=degraded_reasons,
        failures=failures or None,
        cache=cache_meta or None,
    )
