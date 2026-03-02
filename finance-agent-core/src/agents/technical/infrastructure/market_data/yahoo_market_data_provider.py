from __future__ import annotations

import pandas as pd

from .yahoo_ohlcv_provider import fetch_daily_ohlcv
from .yahoo_risk_free_rate_provider import fetch_risk_free_series


class YahooMarketDataProvider:
    def fetch_daily_ohlcv(
        self, ticker_symbol: str, period: str = "5y"
    ) -> pd.DataFrame | None:
        return fetch_daily_ohlcv(ticker_symbol, period=period)

    def fetch_risk_free_series(self, period: str = "5y") -> pd.Series | None:
        return fetch_risk_free_series(period=period)
