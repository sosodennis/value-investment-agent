from __future__ import annotations

from src.agents.technical.subdomains.market_data.application.ports import (
    MarketDataCacheConfig,
    MarketDataOhlcvFetchResult,
    MarketDataRetryPolicy,
    MarketDataRiskFreeRateFetchResult,
)

from .yahoo_ohlcv_provider import fetch_ohlcv
from .yahoo_risk_free_rate_provider import fetch_risk_free_series


class YahooMarketDataProvider:
    def __init__(
        self,
        *,
        cache: MarketDataCacheConfig = MarketDataCacheConfig(),
        retry_policy: MarketDataRetryPolicy = MarketDataRetryPolicy(),
    ) -> None:
        self._cache = cache
        self._retry_policy = retry_policy

    def fetch_ohlcv(
        self,
        ticker_symbol: str,
        *,
        period: str = "5y",
        interval: str = "1d",
    ) -> MarketDataOhlcvFetchResult:
        return fetch_ohlcv(
            ticker_symbol,
            period=period,
            interval=interval,
            cache_base_dir=self._cache.base_dir,
            cache_key_prefix=self._cache.namespace,
            max_retries=self._retry_policy.max_retries,
            retry_delay_seconds=self._retry_policy.delay_seconds,
        )

    def fetch_risk_free_series(
        self, period: str = "5y"
    ) -> MarketDataRiskFreeRateFetchResult:
        return fetch_risk_free_series(period=period)
