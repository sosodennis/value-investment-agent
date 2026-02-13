import logging

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


def fetch_risk_free_series(period: str = "5y") -> pd.Series | None:
    """
    Fetch historical risk-free rate (10-Year Treasury Yield - ^TNX).
    """
    try:
        logger.info(f"--- TA: Fetching Risk-Free Rate (^TNX) for {period} ---")
        tnx = yf.Ticker("^TNX")
        hist = tnx.history(period=period, interval="1d")

        if hist.empty:
            logger.warning("⚠️ Failed to fetch ^TNX, system will use fallback rate.")
            return None

        daily_rf = (hist["Close"] / 100.0) / 252.0
        daily_rf = daily_rf.ffill().fillna(0.0)
        daily_rf = daily_rf.clip(lower=0.0)

        logger.info(f"✅ Fetched {len(daily_rf)} days of risk-free rate data")
        return daily_rf

    except Exception as e:
        logger.error(f"❌ Error fetching risk-free rate: {e}")
        return None
