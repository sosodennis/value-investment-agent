import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller

from .fracdiff import frac_diff_ffd


def calculate_fd_bollinger(
    fd_series: pd.Series, window: int = 20, num_std: float = 2.5
) -> dict:
    """
    Calculate FD-Bollinger (Fractional Differentiation Bollinger Bands).
    """
    s = pd.Series(fd_series.values.flatten(), index=fd_series.index)

    middle = s.rolling(window=window).mean()
    std = s.rolling(window=window).std()

    upper = middle + (std * num_std)
    lower = middle - (std * num_std)

    current_val = s.iloc[-1]
    last_upper = upper.iloc[-1]
    last_lower = lower.iloc[-1]

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
        "series_upper": upper,
        "series_lower": lower,
    }


def calculate_dynamic_thresholds(series: pd.Series, window: int = 252) -> dict:
    """
    Calculate adaptive thresholds based on historical percentiles.
    """
    s = pd.Series(series.flatten()) if isinstance(series, np.ndarray) else series
    recent_data = s.tail(window)

    return {
        "extreme_high": float(recent_data.quantile(0.95)),
        "high": float(recent_data.quantile(0.80)),
        "low": float(recent_data.quantile(0.20)),
        "extreme_low": float(recent_data.quantile(0.05)),
    }


def calculate_fd_macd(
    fd_series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> dict:
    """
    Calculate FD-MACD (Fractional Differentiation MACD).
    """
    s = pd.Series(fd_series.values.flatten(), index=fd_series.index)

    ema_fast = s.ewm(span=fast, adjust=False).mean()
    ema_slow = s.ewm(span=slow, adjust=False).mean()

    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    hist_val = histogram.iloc[-1]
    prev_hist_val = histogram.iloc[-2] if len(histogram) > 1 else hist_val

    momentum = "NEUTRAL"
    if hist_val > 0 and hist_val > prev_hist_val:
        momentum = "BULLISH_EXPANDING"
    elif hist_val > 0 and hist_val < prev_hist_val:
        momentum = "BULLISH_WANING"
    elif hist_val < 0 and hist_val < prev_hist_val:
        momentum = "BEARISH_EXPANDING"
    elif hist_val < 0 and hist_val > prev_hist_val:
        momentum = "BEARISH_WANING"

    return {
        "macd": float(macd_line.iloc[-1]),
        "signal": float(signal_line.iloc[-1]),
        "hist": float(hist_val),
        "momentum_state": momentum,
    }


def calculate_fd_obv(price_series: pd.Series, volume_series: pd.Series) -> dict:
    """
    Calculate FD-OBV using Independent Dynamic Optimization.
    """
    change = price_series.diff()
    direction = np.where(change > 0, 1, np.where(change < 0, -1, 0))
    raw_obv = (direction * volume_series).cumsum().fillna(0)

    optimal_d_obv = 0.4  # Fallback

    for d_candidate in np.arange(0.1, 1.0, 0.1):
        try:
            test_series = frac_diff_ffd(raw_obv, d_candidate)
            if len(test_series) < 100:
                continue

            res = adfuller(test_series.values, regression="c", autolag="AIC")
            pval = res[1]

            if pval < 0.05:
                optimal_d_obv = d_candidate
                break
        except Exception:
            continue

    fd_obv_series = frac_diff_ffd(raw_obv, optimal_d_obv)

    lookback = min(len(fd_obv_series), 126)
    recent = fd_obv_series.iloc[-lookback:]

    std_val = recent.std()
    if std_val < 1e-6:
        z_score_obv = 0.0
    else:
        z_score_obv = (fd_obv_series.iloc[-1] - recent.mean()) / std_val

    rolling_mean = fd_obv_series.rolling(window=lookback).mean()
    rolling_std = fd_obv_series.rolling(window=lookback).std()

    z_score_series = (fd_obv_series - rolling_mean) / rolling_std
    z_score_series = z_score_series.fillna(0.0)

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
        "series_z": z_score_series,
    }
