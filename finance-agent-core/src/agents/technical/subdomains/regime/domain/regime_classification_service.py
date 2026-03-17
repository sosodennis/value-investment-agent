from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from src.agents.technical.domain.shared import PriceSeries
from src.agents.technical.subdomains.features.domain import (
    compute_adx,
    compute_atr,
    compute_bollinger,
    compute_ema,
    compute_macd,
)

from .regime_pack import RegimeFrame


@dataclass(frozen=True)
class RegimeClassificationResult:
    frame: RegimeFrame | None
    degraded_reasons: list[str]


def classify_regime_frame(
    series: PriceSeries,
    *,
    timeframe: str,
) -> RegimeClassificationResult:
    close = _clean_series(series.close_series or series.price_series)
    if close.empty or len(close) < 30:
        return RegimeClassificationResult(
            frame=None, degraded_reasons=["REGIME_INSUFFICIENT_POINTS"]
        )

    high = _clean_series(series.high_series)
    low = _clean_series(series.low_series)
    metadata = series.metadata if isinstance(series.metadata, dict) else {}
    degraded: list[str] = []

    atr_value = _metadata_float(metadata, "regime_input_atr_14")
    atrp_value = _metadata_float(metadata, "regime_input_atrp_14")
    adx_value = _metadata_float(metadata, "regime_input_adx_14")
    bandwidth_value = _metadata_float(metadata, "regime_input_bb_bandwidth_20")

    if (atr_value is None or adx_value is None) and (high is None or low is None):
        degraded.append("REGIME_OHLC_MISSING")
    elif high is not None and low is not None:
        if atr_value is None:
            atr_series = compute_atr(high, low, close, window=14)
            atr_value = _latest_value(atr_series)
        if adx_value is None:
            adx_value = _latest_value(compute_adx(high, low, close, window=14))

    if atr_value is None:
        atr_value = _fallback_atr_from_close(close)
        degraded.append("REGIME_ATR_FALLBACK")

    last_close = float(close.iloc[-1])
    if atrp_value is None:
        atrp_value = float(atr_value / max(abs(last_close), 1e-6))

    ema_20 = _latest_value(compute_ema(close, window=20))
    ema_50 = _latest_value(compute_ema(close, window=50))
    macd_line, macd_signal, _ = compute_macd(close)
    macd_value = _latest_value(macd_line)
    macd_signal_value = _latest_value(macd_signal)

    if bandwidth_value is None:
        bb_upper, bb_middle, bb_lower = compute_bollinger(
            close,
            window=20,
            num_std=2.0,
        )
        bandwidth_value = _bollinger_bandwidth(
            upper=_latest_value(bb_upper),
            middle=_latest_value(bb_middle),
            lower=_latest_value(bb_lower),
        )

    directional_bias, bias_score = _directional_bias(
        close_value=last_close,
        ema_20=ema_20,
        ema_50=ema_50,
        macd_value=macd_value,
        macd_signal_value=macd_signal_value,
    )
    regime, confidence, evidence = _classify_regime(
        directional_bias=directional_bias,
        bias_score=bias_score,
        adx_value=adx_value,
        atrp_value=atrp_value,
        bandwidth_value=bandwidth_value,
    )

    return RegimeClassificationResult(
        frame=RegimeFrame(
            timeframe=timeframe,
            regime=regime,
            confidence=confidence,
            directional_bias=directional_bias,
            adx=adx_value,
            atr_value=atr_value,
            atrp_value=atrp_value,
            bollinger_bandwidth=bandwidth_value,
            evidence=tuple(evidence),
            metadata={"bias_score": bias_score},
        ),
        degraded_reasons=degraded,
    )


def build_regime_summary(
    frames: dict[str, RegimeFrame],
) -> dict[str, float | int | str | bool | None]:
    if not frames:
        return {"timeframe_count": 0, "dominant_regime": None}

    counts: dict[str, int] = {}
    for frame in frames.values():
        counts[frame.regime] = counts.get(frame.regime, 0) + 1
    dominant_regime = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    avg_confidence = _average(
        [frame.confidence for frame in frames.values() if frame.confidence is not None]
    )
    return {
        "timeframe_count": len(frames),
        "dominant_regime": dominant_regime,
        "average_confidence": avg_confidence,
    }


def _classify_regime(
    *,
    directional_bias: str,
    bias_score: int,
    adx_value: float | None,
    atrp_value: float,
    bandwidth_value: float | None,
) -> tuple[str, float, list[str]]:
    evidence: list[str] = [f"bias={directional_bias}"]
    adx_val = adx_value if adx_value is not None else 0.0
    bw_val = bandwidth_value if bandwidth_value is not None else 0.0
    evidence.append(f"adx={adx_val:.2f}")
    evidence.append(f"atrp={atrp_value:.4f}")
    evidence.append(f"bb_bw={bw_val:.4f}")

    if adx_value is not None and adx_value >= 25.0 and directional_bias == "bullish":
        confidence = _bounded_confidence(
            0.55
            + min(0.25, (adx_value - 25.0) / 50.0)
            + min(0.15, max(bias_score - 2, 0) * 0.1)
        )
        return "BULL_TREND", confidence, evidence

    if adx_value is not None and adx_value >= 25.0 and directional_bias == "bearish":
        confidence = _bounded_confidence(
            0.55
            + min(0.25, (adx_value - 25.0) / 50.0)
            + min(0.15, max(abs(bias_score) - 2, 0) * 0.1)
        )
        return "BEAR_TREND", confidence, evidence

    if atrp_value >= 0.035 or bw_val >= 0.12:
        confidence = _bounded_confidence(
            0.5 + min(0.25, atrp_value / 0.1) + min(0.15, bw_val / 0.2)
        )
        return "HIGH_VOL_CHOP", confidence, evidence

    confidence = _bounded_confidence(
        0.45
        + min(0.2, max(0.03 - atrp_value, 0.0) / 0.03)
        + min(0.2, max(0.08 - bw_val, 0.0) / 0.08)
    )
    return "QUIET_MEAN_REVERSION", confidence, evidence


def _directional_bias(
    *,
    close_value: float,
    ema_20: float | None,
    ema_50: float | None,
    macd_value: float | None,
    macd_signal_value: float | None,
) -> tuple[str, int]:
    score = 0
    if ema_20 is not None:
        score += 1 if close_value > ema_20 else -1
    if ema_20 is not None and ema_50 is not None:
        score += 1 if ema_20 > ema_50 else -1
    if macd_value is not None and macd_signal_value is not None:
        if macd_value > macd_signal_value:
            score += 1
        elif macd_value < macd_signal_value:
            score -= 1

    if score >= 2:
        return "bullish", score
    if score <= -2:
        return "bearish", score
    return "neutral", score


def _fallback_atr_from_close(close: pd.Series, *, window: int = 14) -> float:
    diffs = close.diff().abs().rolling(window=window, min_periods=2).mean().dropna()
    if diffs.empty:
        return float(abs(close.iloc[-1]) * 0.0025)
    return float(diffs.iloc[-1])


def _bollinger_bandwidth(
    *,
    upper: float | None,
    middle: float | None,
    lower: float | None,
) -> float | None:
    if upper is None or middle is None or lower is None or abs(middle) < 1e-6:
        return None
    return float((upper - lower) / abs(middle))


def _clean_series(payload: dict[str, float | int | None] | None) -> pd.Series | None:
    if not payload:
        return None
    series = pd.Series(payload)
    try:
        series.index = pd.to_datetime(series.index)
    except Exception:
        pass
    series = series.sort_index()
    series = pd.to_numeric(series, errors="coerce")
    series = series.replace([math.inf, -math.inf], math.nan)
    series = series.dropna()
    return series if not series.empty else None


def _latest_value(series: pd.Series | None) -> float | None:
    if series is None or series.empty:
        return None
    value = series.iloc[-1]
    if pd.isna(value):
        return None
    return float(value)


def _metadata_float(metadata: dict[str, object], key: str) -> float | None:
    raw = metadata.get(key)
    if isinstance(raw, bool):
        return None
    if not isinstance(raw, int | float):
        return None
    value = float(raw)
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 3)


def _bounded_confidence(value: float) -> float:
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return round(max(0.0, min(1.0, value)), 2)
