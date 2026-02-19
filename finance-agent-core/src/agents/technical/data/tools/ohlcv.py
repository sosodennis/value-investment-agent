import logging
import warnings

import pandas as pd
import yfinance as yf

from src.shared.kernel.tools.logger import get_logger, log_event

logger = get_logger(__name__)

# Suppress yfinance warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="yfinance")


def fetch_daily_ohlcv(ticker_symbol: str, period: str = "5y") -> pd.DataFrame | None:
    """
    Fetch daily OHLCV data and fix splits manually to avoid look-ahead bias.
    """
    try:
        log_event(
            logger,
            event="technical_ohlcv_fetch_started",
            message="technical ohlcv fetch started",
            fields={"ticker": ticker_symbol, "period": period},
        )
        ticker = yf.Ticker(ticker_symbol)

        # Download UNADJUSTED history and splits
        df = ticker.history(period=period, interval="1d", auto_adjust=False)
        splits = ticker.splits

        if df.empty:
            log_event(
                logger,
                event="technical_ohlcv_fetch_empty",
                message="technical ohlcv fetch returned no data",
                level=logging.WARNING,
                error_code="TECHNICAL_OHLCV_EMPTY",
                fields={"ticker": ticker_symbol, "period": period},
            )
            return None

        # Fix splits manually: Price = Unadjusted Close / Cumulative Split Factor
        if not splits.empty:
            log_event(
                logger,
                event="technical_ohlcv_split_adjustment",
                message="technical ohlcv applying split adjustments",
                fields={"ticker": ticker_symbol, "split_count": len(splits)},
            )
            split_factors = pd.Series(1.0, index=df.index)
            for date, ratio in splits.items():
                # Apply split ratio to all data BEFORE the split date
                split_factors.loc[df.index < date] *= ratio

            df["price"] = df["Close"] / split_factors
        else:
            df["price"] = df["Close"]

        # Final cleanup - include both price and volume
        # Note: yfinance Volume is already split-adjusted
        final_df = df[["price", "Volume"]].copy()
        final_df.rename(columns={"Volume": "volume"}, inplace=True)

        # --- 🔴 在這裡加入驗證代碼 (Debug Block) ---
        latest_date = final_df.index[-1]
        latest_price = final_df["price"].iloc[-1]
        latest_vol = final_df["volume"].iloc[-1]

        log_event(
            logger,
            event="technical_ohlcv_fetch_completed",
            message="technical ohlcv fetch completed",
            fields={
                "ticker": ticker_symbol,
                "rows": len(final_df),
                "latest_date": str(latest_date),
                "latest_price": float(latest_price),
                "latest_volume": float(latest_vol),
            },
        )
        return final_df

    except Exception as e:
        log_event(
            logger,
            event="technical_ohlcv_fetch_failed",
            message="technical ohlcv fetch failed",
            level=logging.ERROR,
            error_code="TECHNICAL_OHLCV_FETCH_FAILED",
            fields={"ticker": ticker_symbol, "period": period, "exception": str(e)},
        )
        return None
