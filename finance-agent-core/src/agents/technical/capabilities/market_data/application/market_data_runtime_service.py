from __future__ import annotations

from dataclasses import dataclass

from .multi_timeframe_fetch_service import (
    MultiTimeframeFetchRequest,
    fetch_timeseries_bundle,
)
from .ports import (
    IMarketDataProvider,
    MarketDataOhlcvFetchResult,
    MarketDataRiskFreeRateFetchResult,
    MarketDataTimeseriesBundleResult,
)


@dataclass(frozen=True)
class MarketDataRuntimeService:
    provider: IMarketDataProvider

    def fetch_ohlcv(
        self,
        ticker_symbol: str,
        *,
        period: str = "5y",
        interval: str = "1d",
    ) -> MarketDataOhlcvFetchResult:
        return self.provider.fetch_ohlcv(
            ticker_symbol,
            period=period,
            interval=interval,
        )

    def fetch_risk_free_series(
        self, period: str = "5y"
    ) -> MarketDataRiskFreeRateFetchResult:
        return self.provider.fetch_risk_free_series(period=period)

    def fetch_timeseries_bundle(
        self,
        request: MultiTimeframeFetchRequest,
    ) -> MarketDataTimeseriesBundleResult:
        return fetch_timeseries_bundle(self.provider, request)
