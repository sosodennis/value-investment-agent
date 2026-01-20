"""
Core tools for Technical Analysis: data fetching and FracDiff computation.

Uses yfinance for daily OHLCV data and fracdiff library for stationary transformation.
"""

import warnings
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf
from statsmodels.tsa.stattools import adfuller

from src.utils.logger import get_logger

logger = get_logger(__name__)

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


def get_weights_ffd(d: float, thres: float = 1e-4) -> np.ndarray:
    """
    Calculate weights for Fixed-Width Window FracDiff (FFD).
    """
    w = [1.0]
    k = 1
    while True:
        w_next = -w[-1] / k * (d - k + 1)
        if abs(w_next) < thres:
            break
        w.append(w_next)
        k += 1
    return np.array(w[::-1])


def frac_diff_ffd(series: pd.Series, d: float, thres: float = 1e-4) -> pd.Series:
    """
    Apply Fixed-Width Window Fractional Differentiation (FFD).
    """
    w = get_weights_ffd(d, thres)
    width = len(w) - 1
    df = {}

    for i in range(width, series.shape[0]):
        loc0, loc1 = series.index[i - width], series.index[i]
        df[loc1] = np.dot(w, series.loc[loc0:loc1])

    return pd.Series(df)


def find_optimal_d(
    prices: pd.Series, threshold: float = 0.05, max_d: float = 1.0, step: float = 0.05
) -> tuple[float, int, float, float]:
    """
    Find minimum d value that achieves ADF stationarity using LOG-PRICES and FFD.
    """
    logger.info("--- TA: Searching for optimal d value (FFD) ---")

    # 必須轉換為 Log Prices 以消除異方差性
    # [Defensive] Filter out zero or negative prices before log transform
    if (prices <= 0).any():
        logger.warning(
            "⚠️ Detected zero or negative prices. Filtering them out for log transform."
        )
        prices = prices[prices > 0]

    log_prices = np.log(prices)
    # [Defensive] Remove any inf/-inf values that might have slipped through
    log_prices = log_prices.replace([np.inf, -np.inf], np.nan).dropna()

    d_values = np.arange(0.1, max_d + step, step)
    optimal_d = None
    adf_stat = None
    adf_pvalue = None

    for d in d_values:
        try:
            # Apply FFD on LOG prices
            fd_series = frac_diff_ffd(log_prices, d)

            if len(fd_series) < 100:
                continue

            # Run ADF test
            result = adfuller(fd_series.values, regression="c", autolag="AIC")
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
        fd_series = frac_diff_ffd(log_prices, 1.0)
        result = adfuller(fd_series.values, regression="c")
        adf_stat, adf_pvalue = result[0], result[1]

    # Window length for FFD is derived from d
    w = get_weights_ffd(optimal_d)
    window_length = len(w)

    return float(optimal_d), int(window_length), float(adf_stat), float(adf_pvalue)


def apply_fracdiff(prices: pd.Series, d: float) -> pd.Series:
    """
    Apply Fixed-Width Window Fractional Differentiation to LOG prices.
    """
    logger.info(f"--- TA: Applying FFD FracDiff with d={d:.3f} ---")

    try:
        # [Defensive] Filter out zero or negative prices
        if (prices <= 0).any():
            logger.warning(
                "⚠️ Detected zero or negative prices in apply_fracdiff. Filtering."
            )
            prices = prices[prices > 0]

        log_prices = np.log(prices)
        log_prices = log_prices.replace([np.inf, -np.inf], np.nan).dropna()

        fd_series = frac_diff_ffd(log_prices, d)

        logger.info(f"✅ Generated FFD series with {len(fd_series)} values")
        return fd_series

    except Exception as e:
        logger.error(f"❌ FFD FracDiff computation failed: {e}")
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


def calculate_fd_bollinger(
    fd_series: pd.Series, window: int = 20, num_std: float = 2.5
) -> dict:
    """
    Calculate FD-Bollinger (Fractional Differentiation Bollinger Bands).
    Uses 2.5 std dev for institutional-grade filtering.
    """
    # Ensure 1D data
    s = pd.Series(fd_series.values.flatten(), index=fd_series.index)

    # Calculate middle band (moving average)
    middle = s.rolling(window=window).mean()
    # Calculate standard deviation
    std = s.rolling(window=window).std()

    upper = middle + (std * num_std)
    lower = middle - (std * num_std)

    # Get latest values
    current_val = s.iloc[-1]
    last_upper = upper.iloc[-1]
    last_lower = lower.iloc[-1]

    # Determine state
    state = "INSIDE"
    if current_val > last_upper:
        state = "BREAKOUT_UPPER"
    elif current_val < last_lower:
        state = "BREAKOUT_LOWER"

    return {
        "upper": float(last_upper),
        "middle": float(middle.iloc[-1]),
        "lower": float(last_lower),
        "state": state,
        "bandwidth": float(last_upper - last_lower),
        # --- NEW FIELDS FOR BACKTESTER ---
        "series_upper": upper,
        "series_lower": lower,
    }


def calculate_dynamic_thresholds(series: pd.Series, window: int = 252) -> dict:
    """
    Calculate adaptive thresholds based on historical percentiles.
    This prevents hardcoded thresholds from failing on different volatility regimes.
    """
    s = pd.Series(series.flatten()) if isinstance(series, np.ndarray) else series
    recent_data = s.tail(window)

    return {
        "extreme_high": float(recent_data.quantile(0.95)),
        "high": float(recent_data.quantile(0.80)),
        "low": float(recent_data.quantile(0.20)),
        "extreme_low": float(recent_data.quantile(0.05)),
    }


def calculate_fd_rsi_metrics(fd_series: pd.Series, window: int = 14) -> dict:
    """
    Calculate FD-RSI (Type B / Stochastic Style) with dynamic thresholds.
    Returns both the current value and stock-specific thresholds.
    Uses pure vectorization for performance.
    """
    s = pd.Series(fd_series.values.flatten(), index=fd_series.index)

    # Calculate rolling min/max for the entire series (vectorized)
    rolling_min = s.rolling(window=window).min()
    rolling_max = s.rolling(window=window).max()

    # Calculate current RSI value
    current_val = s.iloc[-1]
    c_min = rolling_min.iloc[-1]
    c_max = rolling_max.iloc[-1]

    # Edge case: max == min
    if c_max == c_min:
        rsi_score = 50.0
    else:
        # Calculate position percentage (0-100)
        rsi_score = (current_val - c_min) / (c_max - c_min) * 100.0

    # Boundary limit
    rsi_score = float(max(0.0, min(100.0, rsi_score)))

    # [Vectorized] Build full RSI series for threshold calculation
    # Calculate the range (max - min) for each window
    range_vals = rolling_max - rolling_min

    # Vectorized RSI calculation: (value - min) / (max - min) * 100
    # Handle division by zero by replacing with 50.0
    rsi_series = ((s - rolling_min) / range_vals * 100.0).fillna(50.0)

    # Replace any remaining inf values with 50.0
    rsi_series = rsi_series.replace([np.inf, -np.inf], 50.0)

    # Drop NaN values from the beginning (first 'window' values)
    rsi_series = rsi_series.dropna()

    # Calculate dynamic thresholds for this specific stock
    thresholds = calculate_dynamic_thresholds(rsi_series, window=252)

    return {
        "value": rsi_score,
        "thresholds": thresholds,
        # --- NEW FIELD FOR BACKTESTER ---
        "series_value": rsi_series,  # Full historical RSI series
    }


def calculate_fd_macd(
    fd_series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> dict:
    """
    Calculate FD-MACD (Fractional Differentiation MACD).
    Measures memory structure's "acceleration".
    """
    s = pd.Series(fd_series.values.flatten(), index=fd_series.index)

    # Calculate EMAs
    ema_fast = s.ewm(span=fast, adjust=False).mean()
    ema_slow = s.ewm(span=slow, adjust=False).mean()

    # Calculate MACD line
    macd_line = ema_fast - ema_slow

    # Calculate signal line
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()

    # Calculate histogram
    histogram = macd_line - signal_line

    # Determine momentum state
    hist_val = histogram.iloc[-1]
    prev_hist_val = histogram.iloc[-2] if len(histogram) > 1 else hist_val

    momentum = "NEUTRAL"
    if hist_val > 0 and hist_val > prev_hist_val:
        momentum = "BULLISH_EXPANDING"  # Red bars growing
    elif hist_val > 0 and hist_val < prev_hist_val:
        momentum = "BULLISH_WANING"  # Red bars shrinking (divergence warning)
    elif hist_val < 0 and hist_val < prev_hist_val:
        momentum = "BEARISH_EXPANDING"  # Green bars growing
    elif hist_val < 0 and hist_val > prev_hist_val:
        momentum = "BEARISH_WANING"  # Green bars shrinking (bounce warning)

    return {
        "macd": float(macd_line.iloc[-1]),
        "signal": float(signal_line.iloc[-1]),
        "hist": float(hist_val),
        "momentum_state": momentum,
    }


def calculate_fd_obv(price_series: pd.Series, volume_series: pd.Series) -> dict:
    """
    Calculate FD-OBV using Independent Dynamic Optimization.
    Instead of guessing d=0.4, we calculate the optimal d specifically for the OBV series.
    OBV is additive (not multiplicative like price), so no log transform is needed.
    """
    # 1. Calculate traditional OBV (The Cumulative Series)
    change = price_series.diff()
    direction = np.where(change > 0, 1, np.where(change < 0, -1, 0))
    raw_obv = (direction * volume_series).cumsum().fillna(0)

    # 2. [Enterprise Upgrade] Find optimal d specifically for OBV
    # OBV is an additive series and can be negative, so we don't use log transform
    optimal_d_obv = 0.4  # Fallback

    # Search range: 0.1 to 0.9 (Volume often needs higher d)
    for d_candidate in np.arange(0.1, 1.0, 0.1):
        try:
            test_series = frac_diff_ffd(raw_obv, d_candidate)
            # Check length to ensure ADF is valid
            if len(test_series) < 100:
                continue

            # ADF Test (regression="c" for constant term)
            res = adfuller(test_series.values, regression="c", autolag="AIC")
            pval = res[1]

            if pval < 0.05:  # Standard 5% significance
                optimal_d_obv = d_candidate
                logger.info(
                    f"✅ Found optimal OBV d={optimal_d_obv:.2f} (p-value={pval:.4f})"
                )
                break
        except Exception:
            continue

    # 3. Apply FracDiff with the specific d found for OBV
    fd_obv_series = frac_diff_ffd(raw_obv, optimal_d_obv)

    # 4. Calculate Z-Score (Current value)
    lookback = min(len(fd_obv_series), 126)
    recent = fd_obv_series.iloc[-lookback:]

    std_val = recent.std()
    if std_val < 1e-6:
        z_score_obv = 0.0
    else:
        z_score_obv = (fd_obv_series.iloc[-1] - recent.mean()) / std_val

    # [NEW] Calculate full Z-Score series for backtesting (Vectorized)
    # Use rolling mean/std to calculate historical Z-Score series
    rolling_mean = fd_obv_series.rolling(window=lookback).mean()
    rolling_std = fd_obv_series.rolling(window=lookback).std()

    # Avoid division by zero
    z_score_series = (fd_obv_series - rolling_mean) / rolling_std
    z_score_series = z_score_series.fillna(0.0)

    # 5. Determine State
    state = "NEUTRAL"
    if z_score_obv > 2.0:
        state = "ACCUMULATION_ANOMALY"
    elif z_score_obv < -2.0:
        state = "DISTRIBUTION_ANOMALY"
    elif z_score_obv > 1.0:
        state = "MILD_ACCUMULATION"
    elif z_score_obv < -1.0:
        state = "MILD_DISTRIBUTION"

    return {
        "raw_obv_val": float(raw_obv.iloc[-1]),
        "fd_obv_z": float(z_score_obv),
        "optimal_d": float(optimal_d_obv),
        "state": state,
        # --- NEW FIELD FOR BACKTESTER ---
        "series_z": z_score_series,  # Full historical OBV Z-Score series
    }
