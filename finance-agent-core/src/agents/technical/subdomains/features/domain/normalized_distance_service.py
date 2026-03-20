from __future__ import annotations

import numpy as np
import pandas as pd

from .classic import compute_atr


def compute_price_vs_sma_zscore(
    prices: pd.Series,
    *,
    window: int = 20,
) -> pd.Series:
    if prices.empty:
        return pd.Series(dtype=float)
    sma = prices.rolling(window=window, min_periods=window).mean()
    rolling_std = (
        prices.rolling(window=window, min_periods=window)
        .std(ddof=0)
        .replace(0.0, np.nan)
    )
    return (prices - sma) / rolling_std


def compute_return_zscore(
    prices: pd.Series,
    *,
    window: int = 20,
) -> pd.Series:
    if prices.empty:
        return pd.Series(dtype=float)
    returns = prices.pct_change()
    rolling_mean = returns.rolling(window=window, min_periods=window).mean()
    rolling_std = (
        returns.rolling(window=window, min_periods=window)
        .std(ddof=0)
        .replace(0.0, np.nan)
    )
    return (returns - rolling_mean) / rolling_std


def compute_atr_normalized_distance(
    prices: pd.Series,
    high: pd.Series,
    low: pd.Series,
    *,
    atr_window: int = 14,
    anchor_window: int = 20,
) -> pd.Series:
    if prices.empty or high.empty or low.empty:
        return pd.Series(dtype=float)
    atr = compute_atr(high, low, prices, window=atr_window)
    if atr is None or atr.empty:
        return pd.Series(dtype=float)
    anchor = prices.rolling(window=anchor_window, min_periods=anchor_window).mean()
    atr = atr.replace(0.0, np.nan)
    return (prices - anchor) / atr
