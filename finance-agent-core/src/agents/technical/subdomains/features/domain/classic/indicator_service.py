from __future__ import annotations

import numpy as np
import pandas as pd


def supports_session_vwap_timeframe(timeframe: str) -> bool:
    return timeframe == "1h"


def compute_sma(prices: pd.Series, window: int = 20) -> pd.Series:
    return prices.rolling(window=window, min_periods=window).mean()


def compute_ema(prices: pd.Series, window: int = 20) -> pd.Series:
    return prices.ewm(span=window, adjust=False, min_periods=window).mean()


def compute_rsi(prices: pd.Series, window: int = 14) -> pd.Series:
    delta = prices.diff()
    gains = delta.clip(lower=0.0)
    losses = (-delta).clip(lower=0.0)

    avg_gain = gains.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(0.0)


def compute_macd(
    prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = prices.ewm(span=fast, adjust=False, min_periods=fast).mean()
    ema_slow = prices.ewm(span=slow, adjust=False, min_periods=slow).mean()

    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    histogram = macd_line - signal_line

    return macd_line, signal_line, histogram


def compute_vwap(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volumes: pd.Series,
) -> pd.Series:
    if high.empty or low.empty or close.empty or volumes.empty:
        return pd.Series(dtype=float)

    typical_price = (high + low + close) / 3.0
    session_key = close.index.normalize()
    cumulative_volume = volumes.groupby(session_key).cumsum()
    cumulative_price_volume = (typical_price * volumes).groupby(session_key).cumsum()
    vwap = cumulative_price_volume / cumulative_volume.replace(0.0, np.nan)
    return vwap


def compute_mfi(
    prices: pd.Series,
    volumes: pd.Series,
    window: int = 14,
) -> pd.Series:
    typical_price = prices
    raw_money_flow = typical_price * volumes
    price_diff = typical_price.diff()

    positive_flow = raw_money_flow.where(price_diff > 0.0, 0.0)
    negative_flow = raw_money_flow.where(price_diff < 0.0, 0.0).abs()

    positive_sum = positive_flow.rolling(window=window, min_periods=window).sum()
    negative_sum = negative_flow.rolling(window=window, min_periods=window).sum()

    money_ratio = positive_sum / negative_sum.replace(0.0, np.nan)
    mfi = 100.0 - (100.0 / (1.0 + money_ratio))
    return mfi.fillna(0.0)


def compute_atr(
    high: pd.Series | None,
    low: pd.Series | None,
    close: pd.Series,
    window: int = 14,
) -> pd.Series | None:
    if high is None or low is None:
        return None

    prev_close = close.shift(1)
    ranges = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    )
    true_range = ranges.max(axis=1)
    atr = true_range.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    return atr


def compute_atrp(
    high: pd.Series | None,
    low: pd.Series | None,
    close: pd.Series,
    window: int = 14,
) -> pd.Series | None:
    atr = compute_atr(high, low, close, window=window)
    if atr is None:
        return None
    denominator = close.abs().replace(0.0, np.nan)
    return atr / denominator


def compute_adx(
    high: pd.Series | None,
    low: pd.Series | None,
    close: pd.Series,
    window: int = 14,
) -> pd.Series | None:
    if high is None or low is None:
        return None

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0.0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0.0), 0.0)

    atr = compute_atr(high, low, close, window=window)
    if atr is None:
        return None

    atr = atr.replace(0.0, np.nan)
    plus_di = (
        100.0
        * plus_dm.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
        / atr
    )
    minus_di = (
        100.0
        * minus_dm.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
        / atr
    )
    dx = (
        (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    ) * 100.0
    return dx.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()


def compute_bollinger(
    prices: pd.Series,
    window: int = 20,
    num_std: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    middle = prices.rolling(window=window, min_periods=window).mean()
    std = prices.rolling(window=window, min_periods=window).std()
    upper = middle + (std * num_std)
    lower = middle - (std * num_std)
    return upper, middle, lower


def compute_bollinger_bandwidth(
    prices: pd.Series,
    window: int = 20,
    num_std: float = 2.0,
) -> pd.Series:
    upper, middle, lower = compute_bollinger(
        prices,
        window=window,
        num_std=num_std,
    )
    denominator = middle.abs().replace(0.0, np.nan)
    return (upper - lower) / denominator
