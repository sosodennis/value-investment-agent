from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from src.agents.technical.domain.shared.timeframe import TimeframeCode


@dataclass(frozen=True)
class MarketDataProviderFailure:
    failure_code: str
    reason: str | None = None
    http_status: int | None = None


@dataclass(frozen=True)
class MarketDataCacheMetadata:
    cache_hit: bool
    cache_age_seconds: float | None = None
    cache_bucket: str | None = None


@dataclass(frozen=True)
class MarketDataOhlcvFetchResult:
    data: pd.DataFrame | None
    failure: MarketDataProviderFailure | None = None
    cache: MarketDataCacheMetadata | None = None


@dataclass(frozen=True)
class MarketDataRiskFreeRateFetchResult:
    data: pd.Series | None
    failure: MarketDataProviderFailure | None = None
    cache: MarketDataCacheMetadata | None = None


@dataclass(frozen=True)
class MarketDataTimeseriesBundleResult:
    frames: dict[TimeframeCode, pd.DataFrame]
    degraded_reasons: list[str]
    failures: dict[TimeframeCode, MarketDataProviderFailure] | None = None
    cache: dict[TimeframeCode, MarketDataCacheMetadata] | None = None


class IMarketDataProvider(Protocol):
    def fetch_ohlcv(
        self,
        ticker_symbol: str,
        *,
        period: str = "5y",
        interval: str = "1d",
    ) -> MarketDataOhlcvFetchResult: ...

    def fetch_risk_free_series(
        self, period: str = "5y"
    ) -> MarketDataRiskFreeRateFetchResult: ...
