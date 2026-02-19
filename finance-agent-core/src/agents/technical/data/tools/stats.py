import logging

import numpy as np
import pandas as pd
from scipy.stats import norm

from src.shared.kernel.tools.logger import get_logger, log_event

logger = get_logger(__name__)


def compute_z_score(fd_series: pd.Series, lookback: int = 126) -> float:
    """
    Compute Z-score of latest FracDiff value vs historical distribution.
    """
    if len(fd_series) < lookback:
        lookback = len(fd_series)

    recent_values = fd_series.iloc[-lookback:]
    mean = recent_values.mean()
    std = recent_values.std()

    if std == 0:
        log_event(
            logger,
            event="technical_zscore_zero_std",
            message="technical z-score fallback due to zero standard deviation",
            level=logging.WARNING,
            error_code="TECHNICAL_ZSCORE_ZERO_STD",
        )
        return 0.0

    latest_value = fd_series.iloc[-1]
    z_score = (latest_value - mean) / std

    return z_score


def calculate_rolling_z_score(fd_series: pd.Series, lookback: int = 126) -> pd.Series:
    """
    Generate the full historical Z-Score series from Raw FracDiff data.
    """
    rolling_mean = fd_series.rolling(window=lookback, min_periods=2).mean()
    rolling_std = fd_series.rolling(window=lookback, min_periods=2).std()

    z_score_series = (fd_series - rolling_mean) / rolling_std
    z_score_series = z_score_series.fillna(0.0).replace([np.inf, -np.inf], 0.0)

    log_event(
        logger,
        event="technical_zscore_rolling_completed",
        message="technical rolling z-score computation completed",
        fields={"rows": len(z_score_series)},
    )
    return z_score_series


def calculate_statistical_strength(z_score_series: pd.Series) -> dict:
    """
    Calculate Statistical Strength (CDF) based on Z-Score.
    """
    if z_score_series.empty:
        return {"value": 50.0, "series_value": pd.Series()}

    cdf_series = pd.Series(norm.cdf(z_score_series) * 100.0, index=z_score_series.index)
    current_val = cdf_series.iloc[-1]

    return {
        "value": float(current_val),
        "series_value": cdf_series,
    }
