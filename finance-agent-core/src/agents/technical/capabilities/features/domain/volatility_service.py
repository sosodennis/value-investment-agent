from __future__ import annotations

import math

import numpy as np
import pandas as pd


def compute_realized_volatility(
    prices: pd.Series,
    *,
    window: int = 20,
    annualization_factor: int = 252,
) -> pd.Series:
    if prices.empty:
        return pd.Series(dtype=float)
    returns = prices.pct_change()
    scale = math.sqrt(float(annualization_factor))
    return returns.rolling(window=window, min_periods=window).std(ddof=0) * scale


def compute_downside_volatility(
    prices: pd.Series,
    *,
    window: int = 20,
    annualization_factor: int = 252,
) -> pd.Series:
    if prices.empty:
        return pd.Series(dtype=float)
    returns = prices.pct_change()
    downside_returns = returns.clip(upper=0.0)
    scale = math.sqrt(float(annualization_factor))
    return (
        downside_returns.pow(2)
        .rolling(window=window, min_periods=window)
        .mean()
        .pow(0.5)
        * scale
    )


def compute_volatility_percentile(
    volatility_series: pd.Series,
    *,
    lookback: int = 252,
) -> pd.Series:
    if volatility_series.empty:
        return pd.Series(dtype=float)

    def _percentile_of_last(window_values: pd.Series) -> float:
        cleaned = window_values.dropna()
        if len(cleaned) < lookback:
            return np.nan
        last_value = cleaned.iloc[-1]
        return float((cleaned <= last_value).sum() / len(cleaned))

    return volatility_series.rolling(window=lookback, min_periods=lookback).apply(
        _percentile_of_last,
        raw=False,
    )


def classify_volatility_regime(percentile: float | None) -> str:
    if percentile is None:
        return "UNAVAILABLE"
    if percentile >= 0.8:
        return "ELEVATED"
    if percentile <= 0.2:
        return "COMPRESSED"
    return "NORMAL"
