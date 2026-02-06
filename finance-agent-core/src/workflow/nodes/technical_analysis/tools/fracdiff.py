import logging

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller

logger = logging.getLogger(__name__)


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
    if (prices <= 0).any():
        logger.warning(
            "⚠️ Detected zero or negative prices. Filtering them out for log transform."
        )
        prices = prices[prices > 0]

    log_prices = np.log(prices)
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


def calculate_rolling_fracdiff(
    prices: pd.Series, lookback_window: int = 252, recalc_step: int = 5
) -> tuple[pd.Series, float, int, float, float]:
    """
    Correct way to apply FracDiff: simulated time flow with NO look-ahead bias.
    """
    logger.info(
        f"--- TA: Calculating rolling FracDiff (window={lookback_window}, step={recalc_step}) ---"
    )

    results = {}
    current_d = 0.5  # Initial guess
    st_stat, st_pval = 0.0, 1.0
    win_len = 0  # Initialize win_len

    prices = prices[prices > 0]

    for t in range(lookback_window, len(prices)):
        current_date = prices.index[t]

        if t % recalc_step == 0 or t == lookback_window:
            history = prices.iloc[t - lookback_window : t + 1]
            current_d, win_len, st_stat, st_pval = find_optimal_d(history)

        start_idx = max(0, t - win_len)
        history_for_fd = prices.iloc[start_idx : t + 1]

        if len(history_for_fd) <= win_len:
            continue

        log_prices_win = (
            np.log(history_for_fd).replace([np.inf, -np.inf], np.nan).dropna()
        )

        fd_val_series = frac_diff_ffd(log_prices_win, current_d)

        if not fd_val_series.empty:
            results[current_date] = fd_val_series.iloc[-1]

    fd_series = pd.Series(results)
    logger.info(f"✅ Generated rolling FracDiff series with {len(fd_series)} values")

    return fd_series, current_d, win_len, st_stat, st_pval
