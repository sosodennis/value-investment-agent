import logging
import warnings

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# Suppress yfinance warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="yfinance")


def fetch_daily_ohlcv(ticker_symbol: str, period: str = "5y") -> pd.DataFrame | None:
    """
    Fetch daily OHLCV data and fix splits manually to avoid look-ahead bias.
    """
    try:
        logger.info(f"--- TA: Fetching {period} daily data for {ticker_symbol} ---")
        ticker = yf.Ticker(ticker_symbol)

        # Download UNADJUSTED history and splits
        df = ticker.history(period=period, interval="1d", auto_adjust=False)
        splits = ticker.splits

        if df.empty:
            logger.warning(f"⚠️  No data returned for {ticker_symbol}")
            return None

        # Fix splits manually: Price = Unadjusted Close / Cumulative Split Factor
        if not splits.empty:
            logger.info(
                f"--- TA: Adjusting {len(splits)} split events for {ticker_symbol} ---"
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

        logger.info(f"🔍 [REAL-TIME CHECK] Ticker: {ticker_symbol}")
        logger.info(f"   📅 Date Index: {latest_date}")
        logger.info(f"   💲 Current Price (Live): {latest_price:.4f}")
        logger.info(f"   📊 Volume (So Far): {latest_vol}")
        # ------------------------------------------

        logger.info(
            f"✅ Fetched and split-adjusted {len(final_df)} daily bars for {ticker_symbol}"
        )
        return final_df

    except Exception as e:
        logger.error(f"❌ Failed to fetch data for {ticker_symbol}: {e}")
        return None
