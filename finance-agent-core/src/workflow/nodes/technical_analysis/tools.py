"""
Core tools for Technical Analysis: data fetching and FracDiff computation.

Uses yfinance for daily OHLCV data and fracdiff library for stationary transformation.
"""

import warnings
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf
from fracdiff import fdiff
from statsmodels.tsa.stattools import adfuller

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Suppress yfinance warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="yfinance")


def fetch_daily_ohlcv(ticker: str, period: str = "5y") -> pd.DataFrame | None:
    """
    Fetch daily OHLCV data via yfinance.

    Args:
        ticker: Stock ticker symbol
        period: Historical period (default: 5y for sufficient FracDiff window)

    Returns:
        DataFrame with OHLCV data or None if fetch fails
    """
    try:
        logger.info(f"--- TA: Fetching {period} daily data for {ticker} ---")
        stock = yf.Ticker(ticker)
        df = stock.history(period=period, interval="1d", auto_adjust=True)

        if df.empty:
            logger.warning(f"⚠️  No data returned for {ticker}")
            return None

        # Use Adjusted Close for price analysis (handles splits/dividends)
        df = df[["Close"]].copy()
        df.columns = ["price"]

        logger.info(f"✅ Fetched {len(df)} daily bars for {ticker}")
        return df

    except Exception as e:
        logger.error(f"❌ Failed to fetch data for {ticker}: {e}")
        return None


def find_optimal_d(
    prices: pd.Series, threshold: float = 0.05, max_d: float = 1.0, step: float = 0.05
) -> tuple[float, int, float, float]:
    """
    Find minimum d value that achieves ADF stationarity using LOG-PRICES.
    """
    logger.info("--- TA: Searching for optimal d value ---")

    # [FIX 1] 必須轉換為 Log Prices 以消除異方差性
    log_prices = np.log(prices.values)

    # [FIX 2] d=0 對於價格序列幾乎不可能成立，且會退化為布林通道
    # 我們從 0.1 開始搜索，強迫算法尋找保留記憶的平穩化解
    d_values = np.arange(0.1, max_d + step, step)

    optimal_d = None
    adf_stat = None
    adf_pvalue = None

    for d in d_values:
        try:
            # Apply FracDiff on LOG prices
            fd_array = fdiff(log_prices, n=d)

            # [FIX 3] 嚴格處理 NaN。FracDiff 會導致前段數據無效
            fd_series_clean = fd_array[~np.isnan(fd_array)]

            if len(fd_series_clean) < 100:  # ADF requires sufficient data
                continue

            # Run ADF test (Regression='c' implies constant term, typical for prices)
            result = adfuller(fd_series_clean, regression="c", autolag="AIC")
            stat, pval = result[0], result[1]

            if pval < threshold:
                optimal_d = d
                adf_stat = stat
                adf_pvalue = pval
                logger.info(f"✅ Found optimal d={d:.2f} (p-value={pval:.4f})")
                break

        except Exception:
            continue

    # Fallback logic
    if optimal_d is None:
        logger.warning("⚠️  No d achieved stationarity, using d=1.0 (Log-Return)")
        optimal_d = 1.0
        fd_array = fdiff(log_prices, n=1.0)
        fd_series_clean = fd_array[~np.isnan(fd_array)]
        result = adfuller(fd_series_clean, regression="c")
        adf_stat, adf_pvalue = result[0], result[1]

    # Window length estimation (heuristics)
    window_length = int(500 + (optimal_d * 500))

    return optimal_d, window_length, adf_stat, adf_pvalue


def apply_fracdiff(prices: pd.Series, d: float) -> pd.Series:
    """
    Apply fractional differentiation to LOG prices.
    """
    logger.info(f"--- TA: Applying FracDiff with d={d:.3f} ---")

    try:
        # [FIX 1] 同樣必須使用 Log Prices
        log_prices = np.log(prices.values)

        fd_array = fdiff(log_prices, n=d)
        fd_series = pd.Series(fd_array, index=prices.index)

        # Remove leading NaN values
        fd_series = fd_series.dropna()

        # [CRITICAL NOTE]
        # 這裡返回的是 "Log-Price 的分數差分"。
        # 其物理意義是：去除了趨勢的價格波動百分比。
        # 數值 0.01 代表相對於長期均衡偏離了 1%。

        logger.info(
            f"✅ Generated FracDiff series (Log-Space) with {len(fd_series)} values"
        )
        return fd_series

    except Exception as e:
        logger.error(f"❌ FracDiff computation failed: {e}")
        raise


def compute_z_score(fd_series: pd.Series, lookback: int = 126) -> float:
    """
    Compute Z-score of latest FracDiff value vs historical distribution.

    Args:
        fd_series: FracDiff series
        lookback: Lookback period for mean/std calculation (default: 126 trading days)

    Returns:
        Z-score of the most recent value
    """
    if len(fd_series) < lookback:
        lookback = len(fd_series)

    recent_values = fd_series.iloc[-lookback:]
    mean = recent_values.mean()
    std = recent_values.std()

    if std == 0:
        logger.warning("⚠️  Zero standard deviation in FracDiff series")
        return 0.0

    latest_value = fd_series.iloc[-1]
    z_score = (latest_value - mean) / std

    logger.info(f"--- TA: Z-score = {z_score:.2f} (mean={mean:.4f}, std={std:.4f}) ---")
    return z_score


def get_timestamp() -> str:
    """Get current timestamp in ISO format."""
    return datetime.utcnow().isoformat() + "Z"
