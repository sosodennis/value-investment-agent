from __future__ import annotations

from src.agents.technical.application.ports import (
    TechnicalOhlcvFetchResult,
    TechnicalRiskFreeRateFetchResult,
)

from .yahoo_ohlcv_provider import fetch_daily_ohlcv
from .yahoo_risk_free_rate_provider import fetch_risk_free_series


class YahooMarketDataProvider:
    def fetch_daily_ohlcv(
        self, ticker_symbol: str, period: str = "5y"
    ) -> TechnicalOhlcvFetchResult:
        return fetch_daily_ohlcv(ticker_symbol, period=period)

    def fetch_risk_free_series(
        self, period: str = "5y"
    ) -> TechnicalRiskFreeRateFetchResult:
        return fetch_risk_free_series(period=period)
