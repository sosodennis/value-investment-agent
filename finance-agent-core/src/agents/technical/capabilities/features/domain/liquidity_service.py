from __future__ import annotations

import numpy as np
import pandas as pd


def compute_average_dollar_volume(
    prices: pd.Series,
    volumes: pd.Series,
    *,
    window: int = 20,
) -> pd.Series:
    if prices.empty or volumes.empty:
        return pd.Series(dtype=float)
    dollar_volume = prices * volumes
    return dollar_volume.rolling(window=window, min_periods=window).mean()


def compute_amihud_illiquidity(
    prices: pd.Series,
    volumes: pd.Series,
    *,
    window: int = 20,
    scale: int = 1_000_000,
) -> pd.Series:
    if prices.empty or volumes.empty:
        return pd.Series(dtype=float)
    returns = prices.pct_change().abs()
    dollar_volume = (prices * volumes).replace(0.0, np.nan)
    illiquidity = returns / dollar_volume
    return illiquidity.rolling(window=window, min_periods=window).mean() * float(scale)


def compute_liquidity_percentile(
    dollar_volume_series: pd.Series,
    *,
    lookback: int = 252,
) -> pd.Series:
    if dollar_volume_series.empty:
        return pd.Series(dtype=float)

    def _percentile_of_last(window_values: pd.Series) -> float:
        cleaned = window_values.dropna()
        if len(cleaned) < lookback:
            return np.nan
        last_value = cleaned.iloc[-1]
        return float((cleaned <= last_value).sum() / len(cleaned))

    return dollar_volume_series.rolling(window=lookback, min_periods=lookback).apply(
        _percentile_of_last,
        raw=False,
    )


def classify_liquidity_regime(percentile: float | None) -> str:
    if percentile is None:
        return "UNAVAILABLE"
    if percentile >= 0.8:
        return "LIQUID"
    if percentile <= 0.2:
        return "THIN"
    return "NORMAL"
