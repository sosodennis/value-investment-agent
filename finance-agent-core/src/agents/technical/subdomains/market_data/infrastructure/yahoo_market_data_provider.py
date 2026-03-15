from __future__ import annotations

from src.agents.technical.subdomains.market_data.application.ports import (
    MarketDataOhlcvFetchResult,
    MarketDataRiskFreeRateFetchResult,
)

from .yahoo_ohlcv_provider import fetch_ohlcv
from .yahoo_risk_free_rate_provider import fetch_risk_free_series


class YahooMarketDataProvider:
    def fetch_ohlcv(
        self,
        ticker_symbol: str,
        *,
        period: str = "5y",
        interval: str = "1d",
    ) -> MarketDataOhlcvFetchResult:
        return fetch_ohlcv(ticker_symbol, period=period, interval=interval)

    def fetch_risk_free_series(
        self, period: str = "5y"
    ) -> MarketDataRiskFreeRateFetchResult:
        return fetch_risk_free_series(period=period)
