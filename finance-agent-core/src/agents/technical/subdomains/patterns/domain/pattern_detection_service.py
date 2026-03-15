from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

from src.agents.technical.domain.shared import (
    KeyLevel,
    PatternFlag,
    PatternFrame,
)


@dataclass(frozen=True)
class PatternDetectionResult:
    frame: PatternFrame
    degraded_reasons: list[str]


def detect_pattern_frame(
    price_series: pd.Series,
    *,
    timeframe: str,
) -> PatternDetectionResult:
    cleaned = _clean_series(price_series)
    if cleaned.empty:
        return PatternDetectionResult(
            frame=PatternFrame(), degraded_reasons=["PRICE_EMPTY"]
        )

    support_levels, resistance_levels = _detect_key_levels(cleaned)
    breakouts = _detect_breakouts(cleaned)
    trendlines, trend_confidence = _detect_trendline(cleaned)
    pattern_flags = _detect_proximity_flags(cleaned, support_levels, resistance_levels)

    confidence_scores = {
        "support_confidence": _average_strength(support_levels),
        "resistance_confidence": _average_strength(resistance_levels),
        "breakout_confidence": _average_flag_confidence(breakouts),
        "trend_confidence": trend_confidence,
    }

    frame = PatternFrame(
        support_levels=support_levels,
        resistance_levels=resistance_levels,
        breakouts=breakouts,
        trendlines=trendlines,
        pattern_flags=pattern_flags,
        confidence_scores=confidence_scores,
    )
    return PatternDetectionResult(frame=frame, degraded_reasons=[])


def build_pattern_summary(
    frames: dict[str, PatternFrame],
) -> dict[str, float | int | str | bool | None]:
    support_count = sum(len(frame.support_levels) for frame in frames.values())
    resistance_count = sum(len(frame.resistance_levels) for frame in frames.values())
    breakout_count = sum(len(frame.breakouts) for frame in frames.values())
    trend_count = sum(len(frame.trendlines) for frame in frames.values())
    return {
        "timeframe_count": len(frames),
        "support_level_count": support_count,
        "resistance_level_count": resistance_count,
        "breakout_count": breakout_count,
        "trendline_count": trend_count,
    }


def _detect_key_levels(
    price_series: pd.Series,
    *,
    max_levels: int = 3,
    tolerance_pct: float = 0.02,
) -> tuple[list[KeyLevel], list[KeyLevel]]:
    values = price_series.values
    if len(values) < 10:
        return [], []

    distance = max(2, int(len(values) * 0.05))
    peaks, _ = find_peaks(values, distance=distance)
    troughs, _ = find_peaks(-values, distance=distance)

    last_price = float(values[-1])
    bin_size = max(abs(last_price) * tolerance_pct, 1e-6)

    resistance_levels = _cluster_levels(
        values,
        peaks,
        bin_size=bin_size,
        max_levels=max_levels,
        last_price=last_price,
        label="RESISTANCE",
    )
    support_levels = _cluster_levels(
        values,
        troughs,
        bin_size=bin_size,
        max_levels=max_levels,
        last_price=last_price,
        label="SUPPORT",
    )
    return support_levels, resistance_levels


def _detect_breakouts(
    price_series: pd.Series,
    *,
    lookback: int = 20,
) -> list[PatternFlag]:
    if len(price_series) <= lookback + 1:
        return []

    recent = price_series.iloc[-(lookback + 1) : -1]
    latest = float(price_series.iloc[-1])
    recent_high = float(recent.max())
    recent_low = float(recent.min())

    if latest > recent_high:
        confidence = _bounded_confidence(
            (latest - recent_high) / max(recent_high, 1e-6)
        )
        return [
            PatternFlag(
                name="BREAKOUT_UP",
                confidence=confidence,
                notes=f"Above {recent_high:.2f}",
            )
        ]
    if latest < recent_low:
        confidence = _bounded_confidence((recent_low - latest) / max(recent_low, 1e-6))
        return [
            PatternFlag(
                name="BREAKOUT_DOWN",
                confidence=confidence,
                notes=f"Below {recent_low:.2f}",
            )
        ]

    return []


def _detect_trendline(
    price_series: pd.Series,
    *,
    window: int = 60,
    slope_threshold: float = 0.0005,
) -> tuple[list[PatternFlag], float]:
    if len(price_series) < 10:
        return [], 0.0

    window = min(window, len(price_series))
    window_series = price_series.iloc[-window:]
    y = window_series.values
    x = np.arange(len(y))
    slope, _ = np.polyfit(x, y, 1)
    last_price = float(y[-1])
    slope_pct = float(slope / max(abs(last_price), 1e-6))

    if abs(slope_pct) < slope_threshold:
        state = "SIDEWAYS"
    elif slope_pct > 0:
        state = "UPTREND"
    else:
        state = "DOWNTREND"

    confidence = _bounded_confidence(abs(slope_pct) / 0.01)
    return (
        [
            PatternFlag(
                name=state,
                confidence=confidence,
                notes=f"slope_pct={slope_pct:.4f}",
            )
        ],
        confidence,
    )


def _detect_proximity_flags(
    price_series: pd.Series,
    support_levels: list[KeyLevel],
    resistance_levels: list[KeyLevel],
    *,
    proximity_pct: float = 0.015,
) -> list[PatternFlag]:
    if price_series.empty:
        return []

    last_price = float(price_series.iloc[-1])
    tolerance = abs(last_price) * proximity_pct
    flags: list[PatternFlag] = []

    for level in support_levels:
        if abs(last_price - level.price) <= tolerance:
            flags.append(
                PatternFlag(
                    name="NEAR_SUPPORT",
                    confidence=_bounded_confidence(
                        1.0 - abs(last_price - level.price) / max(tolerance, 1e-6)
                    ),
                    notes=f"support={level.price:.2f}",
                )
            )
            break

    for level in resistance_levels:
        if abs(last_price - level.price) <= tolerance:
            flags.append(
                PatternFlag(
                    name="NEAR_RESISTANCE",
                    confidence=_bounded_confidence(
                        1.0 - abs(last_price - level.price) / max(tolerance, 1e-6)
                    ),
                    notes=f"resistance={level.price:.2f}",
                )
            )
            break

    return flags


def _cluster_levels(
    values: np.ndarray,
    indices: np.ndarray,
    *,
    bin_size: float,
    max_levels: int,
    last_price: float,
    label: str,
) -> list[KeyLevel]:
    if bin_size <= 0:
        return []
    bins: dict[int, list[float]] = {}
    for idx in indices:
        price = float(values[idx])
        bin_key = int(price / bin_size)
        bins.setdefault(bin_key, []).append(price)

    levels: list[KeyLevel] = []
    for prices in bins.values():
        avg_price = float(np.mean(prices))
        touches = len(prices)
        strength = _bounded_confidence(touches / 5.0)
        levels.append(
            KeyLevel(
                price=avg_price,
                strength=strength,
                touches=touches,
                label=label,
            )
        )

    levels.sort(
        key=lambda level: (
            -(level.touches or 0),
            abs(level.price - last_price),
        )
    )
    return levels[:max_levels]


def _clean_series(series: pd.Series) -> pd.Series:
    if series is None or series.empty:
        return pd.Series(dtype=float)
    cleaned = pd.to_numeric(series, errors="coerce")
    cleaned = cleaned.replace([math.inf, -math.inf], math.nan)
    return cleaned.dropna()


def _average_strength(levels: list[KeyLevel]) -> float:
    if not levels:
        return 0.0
    strengths = [level.strength for level in levels if level.strength is not None]
    if not strengths:
        return 0.0
    return float(sum(strengths) / len(strengths))


def _average_flag_confidence(flags: list[PatternFlag]) -> float:
    confidences = [flag.confidence for flag in flags if flag.confidence is not None]
    if not confidences:
        return 0.0
    return float(sum(confidences) / len(confidences))


def _bounded_confidence(value: float) -> float:
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return float(max(0.0, min(1.0, value)))
