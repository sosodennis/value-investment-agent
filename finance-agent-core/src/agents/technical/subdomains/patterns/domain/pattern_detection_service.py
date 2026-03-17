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
    PriceSeries,
    VolumeProfileSummary,
)


@dataclass(frozen=True)
class PatternDetectionResult:
    frame: PatternFrame
    degraded_reasons: list[str]


@dataclass(frozen=True)
class PatternThresholdProfile:
    atr_value: float
    atrp_value: float
    bin_size: float
    proximity_tolerance: float
    breakout_buffer: float
    slope_atr_floor: float
    degraded_reasons: list[str]


@dataclass(frozen=True)
class VolumeProfileDetectionResult:
    levels: list[KeyLevel]
    summary: VolumeProfileSummary | None
    degraded_reasons: list[str]


def detect_pattern_frame(
    series: PriceSeries,
    *,
    timeframe: str,
) -> PatternDetectionResult:
    cleaned = _clean_series(_series_from_mapping(series.price_series))
    if cleaned.empty:
        return PatternDetectionResult(
            frame=PatternFrame(), degraded_reasons=["PRICE_EMPTY"]
        )

    threshold_profile = _build_threshold_profile(
        price_series=cleaned,
        high_series=_optional_clean_series(series.high_series),
        low_series=_optional_clean_series(series.low_series),
        close_series=_optional_clean_series(series.close_series),
    )
    support_levels, resistance_levels = _detect_key_levels(
        cleaned, bin_size=threshold_profile.bin_size
    )
    breakouts = _detect_breakouts(
        cleaned, breakout_buffer=threshold_profile.breakout_buffer
    )
    trendlines, trend_confidence = _detect_trendline(
        cleaned,
        atr_value=threshold_profile.atr_value,
        slope_atr_floor=threshold_profile.slope_atr_floor,
    )
    pattern_flags = _detect_proximity_flags(
        cleaned,
        support_levels,
        resistance_levels,
        proximity_tolerance=threshold_profile.proximity_tolerance,
    )
    volume_profile_result = _detect_volume_profile(
        price_series=cleaned,
        volume_series=_optional_clean_series(series.volume_series),
        bin_size=threshold_profile.bin_size,
        timeframe=timeframe,
    )
    volume_profile_levels = volume_profile_result.levels
    confluence_metadata = _build_confluence_metadata(
        price_series=cleaned,
        support_levels=support_levels,
        resistance_levels=resistance_levels,
        volume_profile_levels=volume_profile_levels,
        volume_profile_summary=volume_profile_result.summary,
        breakouts=breakouts,
        trendlines=trendlines,
        proximity_tolerance=threshold_profile.proximity_tolerance,
    )

    confidence_scores = {
        "support_confidence": _average_strength(support_levels),
        "resistance_confidence": _average_strength(resistance_levels),
        "volume_profile_confidence": _average_strength(volume_profile_levels),
        "breakout_confidence": _average_flag_confidence(breakouts),
        "trend_confidence": trend_confidence,
        "atr_value": threshold_profile.atr_value,
        "atrp_value": threshold_profile.atrp_value,
        "adaptive_bin_size": threshold_profile.bin_size,
        "adaptive_proximity_tolerance": threshold_profile.proximity_tolerance,
        "adaptive_breakout_buffer": threshold_profile.breakout_buffer,
        "adaptive_slope_atr_floor": threshold_profile.slope_atr_floor,
    }

    frame = PatternFrame(
        support_levels=support_levels,
        resistance_levels=resistance_levels,
        volume_profile_levels=volume_profile_levels,
        volume_profile_summary=volume_profile_result.summary,
        breakouts=breakouts,
        trendlines=trendlines,
        pattern_flags=pattern_flags,
        confluence_metadata=confluence_metadata,
        confidence_scores=confidence_scores,
    )
    return PatternDetectionResult(
        frame=frame,
        degraded_reasons=(
            threshold_profile.degraded_reasons + volume_profile_result.degraded_reasons
        ),
    )


def build_pattern_summary(
    frames: dict[str, PatternFrame],
) -> dict[str, float | int | str | bool | None]:
    support_count = sum(len(frame.support_levels) for frame in frames.values())
    resistance_count = sum(len(frame.resistance_levels) for frame in frames.values())
    volume_profile_count = sum(
        len(frame.volume_profile_levels) for frame in frames.values()
    )
    breakout_count = sum(len(frame.breakouts) for frame in frames.values())
    trend_count = sum(len(frame.trendlines) for frame in frames.values())
    strong_confluence_count = sum(
        1
        for frame in frames.values()
        if float(frame.confluence_metadata.get("confluence_score") or 0.0) >= 0.6
    )
    return {
        "timeframe_count": len(frames),
        "support_level_count": support_count,
        "resistance_level_count": resistance_count,
        "volume_profile_level_count": volume_profile_count,
        "breakout_count": breakout_count,
        "trendline_count": trend_count,
        "strong_confluence_count": strong_confluence_count,
    }


def _detect_key_levels(
    price_series: pd.Series,
    *,
    max_levels: int = 3,
    bin_size: float,
) -> tuple[list[KeyLevel], list[KeyLevel]]:
    values = price_series.values
    if len(values) < 10:
        return [], []

    distance = max(2, int(len(values) * 0.05))
    peaks, _ = find_peaks(values, distance=distance)
    troughs, _ = find_peaks(-values, distance=distance)

    last_price = float(values[-1])
    bin_size = max(bin_size, 1e-6)

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
    breakout_buffer: float,
) -> list[PatternFlag]:
    if len(price_series) <= lookback + 1:
        return []

    recent = price_series.iloc[-(lookback + 1) : -1]
    latest = float(price_series.iloc[-1])
    recent_high = float(recent.max())
    recent_low = float(recent.min())

    if latest > (recent_high + breakout_buffer):
        confidence = _bounded_confidence(
            (latest - recent_high - breakout_buffer) / max(breakout_buffer, 1e-6)
        )
        return [
            PatternFlag(
                name="BREAKOUT_UP",
                confidence=confidence,
                notes=f"Above {recent_high:.2f} by buffer {breakout_buffer:.2f}",
            )
        ]
    if latest < (recent_low - breakout_buffer):
        confidence = _bounded_confidence(
            (recent_low - latest - breakout_buffer) / max(breakout_buffer, 1e-6)
        )
        return [
            PatternFlag(
                name="BREAKOUT_DOWN",
                confidence=confidence,
                notes=f"Below {recent_low:.2f} by buffer {breakout_buffer:.2f}",
            )
        ]

    return []


def _detect_trendline(
    price_series: pd.Series,
    *,
    window: int = 60,
    atr_value: float,
    slope_atr_floor: float,
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
    slope_atr = float(slope / max(atr_value, 1e-6))

    if abs(slope_atr) < slope_atr_floor:
        state = "SIDEWAYS"
    elif slope_atr > 0:
        state = "UPTREND"
    else:
        state = "DOWNTREND"

    confidence = _bounded_confidence(abs(slope_atr) / max(slope_atr_floor * 4.0, 1e-6))
    return (
        [
            PatternFlag(
                name=state,
                confidence=confidence,
                notes=f"slope_pct={slope_pct:.4f}; slope_atr={slope_atr:.3f}",
            )
        ],
        confidence,
    )


def _detect_proximity_flags(
    price_series: pd.Series,
    support_levels: list[KeyLevel],
    resistance_levels: list[KeyLevel],
    *,
    proximity_tolerance: float,
) -> list[PatternFlag]:
    if price_series.empty:
        return []

    last_price = float(price_series.iloc[-1])
    tolerance = max(proximity_tolerance, 1e-6)
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


def _optional_clean_series(
    raw_series: dict[str, float | int | None] | None,
) -> pd.Series | None:
    if raw_series is None:
        return None
    cleaned = _clean_series(_series_from_mapping(raw_series))
    return cleaned if not cleaned.empty else None


def _series_from_mapping(raw_series: dict[str, float | int | None]) -> pd.Series:
    if not raw_series:
        return pd.Series(dtype=float)
    series = pd.Series(raw_series)
    try:
        series.index = pd.to_datetime(series.index)
    except Exception:
        pass
    return series.sort_index()


def _detect_volume_profile(
    *,
    price_series: pd.Series,
    volume_series: pd.Series | None,
    bin_size: float,
    timeframe: str,
    max_levels: int = 3,
) -> VolumeProfileDetectionResult:
    if volume_series is None:
        return VolumeProfileDetectionResult(
            levels=[],
            summary=None,
            degraded_reasons=["VOLUME_PROFILE_VOLUME_MISSING"],
        )

    aligned = pd.concat(
        [price_series.rename("price"), volume_series.rename("volume")],
        axis=1,
        join="inner",
    ).dropna()
    if len(aligned) < 10:
        return VolumeProfileDetectionResult(
            levels=[],
            summary=None,
            degraded_reasons=["VOLUME_PROFILE_ALIGNMENT_EMPTY"],
        )

    bucket_width = max(bin_size, 1e-6)
    profile_totals: dict[float, float] = {}
    bucket_counts: dict[float, int] = {}
    last_price = float(price_series.iloc[-1])
    for row in aligned.itertuples(index=False):
        price = float(row.price)
        volume = max(float(row.volume), 0.0)
        bucket = round(round(price / bucket_width) * bucket_width, 6)
        profile_totals[bucket] = profile_totals.get(bucket, 0.0) + volume
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1

    ranked = sorted(
        profile_totals.items(),
        key=lambda item: (-item[1], abs(item[0] - last_price)),
    )[:max_levels]
    if not ranked:
        return VolumeProfileDetectionResult(
            levels=[],
            summary=None,
            degraded_reasons=["VOLUME_PROFILE_EMPTY"],
        )

    max_volume = ranked[0][1]
    levels = [
        KeyLevel(
            price=price,
            strength=_bounded_confidence(volume / max(max_volume, 1e-6)),
            touches=bucket_counts.get(price),
            label="HVN" if idx == 0 else "VOLUME_NODE",
        )
        for idx, (price, volume) in enumerate(ranked)
    ]
    profile_method = "intraday_approx" if timeframe == "1h" else "daily_bar_approx"
    profile_fidelity = "medium" if timeframe == "1h" else "low"
    poc, vah, val, coverage = _calculate_value_area(profile_totals)
    return VolumeProfileDetectionResult(
        levels=levels,
        summary=VolumeProfileSummary(
            poc=poc,
            vah=vah,
            val=val,
            profile_method=profile_method,
            profile_fidelity=profile_fidelity,
            bucket_count=len(profile_totals),
            value_area_coverage=coverage,
        ),
        degraded_reasons=[],
    )


def _build_confluence_metadata(
    *,
    price_series: pd.Series,
    support_levels: list[KeyLevel],
    resistance_levels: list[KeyLevel],
    volume_profile_levels: list[KeyLevel],
    volume_profile_summary: VolumeProfileSummary | None,
    breakouts: list[PatternFlag],
    trendlines: list[PatternFlag],
    proximity_tolerance: float,
) -> dict[str, float | int | str | bool | list[str] | None]:
    latest_price = float(price_series.iloc[-1])
    nearest_volume = _nearest_level(volume_profile_levels, latest_price)
    nearest_support = _nearest_level(support_levels, latest_price)
    nearest_resistance = _nearest_level(resistance_levels, latest_price)

    near_volume_node = _is_near_level(
        latest_price, nearest_volume, tolerance=proximity_tolerance
    )
    near_support = _is_near_level(
        latest_price, nearest_support, tolerance=proximity_tolerance
    )
    near_resistance = _is_near_level(
        latest_price, nearest_resistance, tolerance=proximity_tolerance
    )

    breakout_bias = _breakout_bias(breakouts)
    trend_bias = _trend_bias(trendlines)
    reasons: list[str] = []
    score = 0.0

    if near_volume_node:
        score += 0.35
        reasons.append("near_volume_node")
    if near_support or near_resistance:
        score += 0.2
        reasons.append("near_key_level")
    if breakout_bias != "neutral":
        score += 0.2
        reasons.append("breakout_signal")
    if trend_bias != "neutral":
        score += 0.15
        reasons.append("trend_alignment")
    if near_volume_node and breakout_bias == trend_bias and breakout_bias != "neutral":
        score += 0.1
        reasons.append("volume_confirms_direction")

    score = round(min(score, 1.0), 3)
    if score >= 0.7:
        confluence_state = "strong"
    elif score >= 0.4:
        confluence_state = "moderate"
    elif score > 0.0:
        confluence_state = "weak"
    else:
        confluence_state = "none"

    return {
        "confluence_score": score,
        "confluence_state": confluence_state,
        "volume_node_count": len(volume_profile_levels),
        "near_volume_node": near_volume_node,
        "near_support": near_support,
        "near_resistance": near_resistance,
        "nearest_volume_node": nearest_volume.price
        if nearest_volume is not None
        else None,
        "nearest_support": nearest_support.price
        if nearest_support is not None
        else None,
        "nearest_resistance": (
            nearest_resistance.price if nearest_resistance is not None else None
        ),
        "poc": volume_profile_summary.poc
        if volume_profile_summary is not None
        else None,
        "vah": volume_profile_summary.vah
        if volume_profile_summary is not None
        else None,
        "val": volume_profile_summary.val
        if volume_profile_summary is not None
        else None,
        "profile_method": (
            volume_profile_summary.profile_method
            if volume_profile_summary is not None
            else None
        ),
        "profile_fidelity": (
            volume_profile_summary.profile_fidelity
            if volume_profile_summary is not None
            else None
        ),
        "breakout_bias": breakout_bias,
        "trend_bias": trend_bias,
        "reasons": reasons,
    }


def _nearest_level(levels: list[KeyLevel], latest_price: float) -> KeyLevel | None:
    if not levels:
        return None
    return min(levels, key=lambda level: abs(level.price - latest_price))


def _is_near_level(
    latest_price: float,
    level: KeyLevel | None,
    *,
    tolerance: float,
) -> bool:
    if level is None:
        return False
    return abs(latest_price - level.price) <= max(tolerance, 1e-6)


def _breakout_bias(flags: list[PatternFlag]) -> str:
    names = {flag.name.upper() for flag in flags}
    if "BREAKOUT_UP" in names:
        return "bullish"
    if "BREAKOUT_DOWN" in names:
        return "bearish"
    return "neutral"


def _trend_bias(flags: list[PatternFlag]) -> str:
    names = {flag.name.upper() for flag in flags}
    if "UPTREND" in names:
        return "bullish"
    if "DOWNTREND" in names:
        return "bearish"
    return "neutral"


def _build_threshold_profile(
    *,
    price_series: pd.Series,
    high_series: pd.Series | None,
    low_series: pd.Series | None,
    close_series: pd.Series | None,
) -> PatternThresholdProfile:
    degraded: list[str] = []
    close = close_series if close_series is not None else price_series
    if high_series is None or low_series is None:
        degraded.append("VOLATILITY_HIGH_LOW_MISSING")
        atr_value = _fallback_atr_from_close(close)
    else:
        aligned = pd.concat(
            [
                high_series.rename("high"),
                low_series.rename("low"),
                close.rename("close"),
            ],
            axis=1,
            join="inner",
        ).dropna()
        if len(aligned) < 2:
            degraded.append("VOLATILITY_ALIGNMENT_EMPTY")
            atr_value = _fallback_atr_from_close(close)
        else:
            atr_value = _atr_from_ohlc(
                aligned["high"], aligned["low"], aligned["close"]
            )

    last_price = (
        float(close.iloc[-1]) if not close.empty else float(price_series.iloc[-1])
    )
    atr_value = max(atr_value, abs(last_price) * 0.0025, 1e-6)
    atrp_value = float(atr_value / max(abs(last_price), 1e-6))
    return PatternThresholdProfile(
        atr_value=atr_value,
        atrp_value=atrp_value,
        bin_size=max(atr_value * 0.75, abs(last_price) * 0.003),
        proximity_tolerance=max(atr_value * 0.5, abs(last_price) * 0.002),
        breakout_buffer=max(atr_value * 0.25, abs(last_price) * 0.001),
        slope_atr_floor=max(0.12, atrp_value * 8.0),
        degraded_reasons=degraded,
    )


def _atr_from_ohlc(
    high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14
) -> float:
    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr_series = true_range.rolling(window=window, min_periods=2).mean().dropna()
    if atr_series.empty:
        return _fallback_atr_from_close(close)
    return float(atr_series.iloc[-1])


def _fallback_atr_from_close(close: pd.Series, window: int = 14) -> float:
    if close.empty:
        return 0.0
    diffs = close.diff().abs().rolling(window=window, min_periods=2).mean().dropna()
    if diffs.empty:
        return float(abs(close.iloc[-1]) * 0.0025)
    return float(diffs.iloc[-1])


def _calculate_value_area(
    profile_totals: dict[float, float],
    *,
    coverage_target: float = 0.7,
) -> tuple[float | None, float | None, float | None, float]:
    if not profile_totals:
        return None, None, None, 0.0
    total_volume = float(sum(profile_totals.values()))
    if total_volume <= 0:
        return None, None, None, 0.0

    ranked = sorted(profile_totals.items(), key=lambda item: item[1], reverse=True)
    selected_prices: list[float] = []
    covered_volume = 0.0
    for price, volume in ranked:
        selected_prices.append(price)
        covered_volume += float(volume)
        if covered_volume / total_volume >= coverage_target:
            break

    poc = float(ranked[0][0]) if ranked else None
    vah = max(selected_prices) if selected_prices else poc
    val = min(selected_prices) if selected_prices else poc
    coverage = round(min(covered_volume / total_volume, 1.0), 4)
    return poc, vah, val, coverage


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
