import logging

import pandas as pd
import yfinance as yf

from src.shared.kernel.tools.logger import get_logger, log_event

logger = get_logger(__name__)


def fetch_risk_free_series(period: str = "5y") -> pd.Series | None:
    """
    Fetch historical risk-free rate (10-Year Treasury Yield - ^TNX).
    """
    try:
        log_event(
            logger,
            event="technical_risk_free_fetch_started",
            message="technical risk-free rate fetch started",
            fields={"period": period},
        )
        tnx = yf.Ticker("^TNX")
        hist = tnx.history(period=period, interval="1d")

        if hist.empty:
            log_event(
                logger,
                event="technical_risk_free_fetch_empty",
                message="technical risk-free rate fetch returned empty data",
                level=logging.WARNING,
                error_code="TECHNICAL_RISK_FREE_EMPTY",
                fields={"period": period},
            )
            return None

        daily_rf = (hist["Close"] / 100.0) / 252.0
        daily_rf = daily_rf.ffill().fillna(0.0)
        daily_rf = daily_rf.clip(lower=0.0)

        log_event(
            logger,
            event="technical_risk_free_fetch_completed",
            message="technical risk-free rate fetch completed",
            fields={"period": period, "rows": len(daily_rf)},
        )
        return daily_rf

    except Exception as e:
        log_event(
            logger,
            event="technical_risk_free_fetch_failed",
            message="technical risk-free rate fetch failed",
            level=logging.ERROR,
            error_code="TECHNICAL_RISK_FREE_FETCH_FAILED",
            fields={"period": period, "exception": str(e)},
        )
        return None
