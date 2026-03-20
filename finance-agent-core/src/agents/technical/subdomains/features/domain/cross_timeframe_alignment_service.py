from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from src.agents.technical.domain.shared import (
    FeatureFrame,
    IndicatorSnapshot,
    TimeframeCode,
)

_PREFERRED_TIMEFRAMES: tuple[TimeframeCode, ...] = ("1d", "1wk", "1h")
_SCALE_ORDER: tuple[TimeframeCode, ...] = ("1h", "1d", "1wk")


@dataclass(frozen=True)
class CrossTimeframeAlignmentResult:
    primary_timeframe: TimeframeCode | None
    primary_bias: str
    dominant_bias: str
    alignment_ratio: float | None
    higher_timeframe: TimeframeCode | None
    higher_bias: str
    higher_confirmation: float | None
    higher_state: str
    lower_timeframe: TimeframeCode | None
    lower_bias: str
    lower_confirmation: float | None
    lower_state: str
    overall_state: str
    aligned_timeframes: tuple[TimeframeCode, ...] = ()
    disagreeing_timeframes: tuple[TimeframeCode, ...] = ()
    neutral_timeframes: tuple[TimeframeCode, ...] = ()


def compute_cross_timeframe_alignment(
    frames: Mapping[TimeframeCode, FeatureFrame],
) -> CrossTimeframeAlignmentResult | None:
    available = {
        timeframe: _classic_bias(frame.classic_indicators)
        for timeframe, frame in frames.items()
        if frame.classic_indicators
    }
    if not available:
        return None

    primary = _select_primary_timeframe(tuple(available))
    if primary is None:
        return None
    primary_bias = available.get(primary, "unavailable")

    non_neutral = {
        timeframe: bias
        for timeframe, bias in available.items()
        if bias in {"bullish", "bearish"}
    }
    dominant_bias = _dominant_bias(non_neutral)
    aligned_timeframes = tuple(
        timeframe
        for timeframe, bias in non_neutral.items()
        if dominant_bias != "neutral" and bias == dominant_bias
    )
    disagreeing_timeframes = tuple(
        timeframe
        for timeframe, bias in non_neutral.items()
        if dominant_bias != "neutral" and bias != dominant_bias
    )
    neutral_timeframes = tuple(
        timeframe for timeframe, bias in available.items() if bias == "neutral"
    )
    alignment_ratio = (
        round(len(aligned_timeframes) / len(non_neutral), 3) if non_neutral else None
    )

    higher_timeframe = _neighbor_timeframe(
        primary, direction="higher", available=available
    )
    lower_timeframe = _neighbor_timeframe(
        primary, direction="lower", available=available
    )
    higher_bias = (
        available.get(higher_timeframe, "unavailable")
        if higher_timeframe
        else "unavailable"
    )
    lower_bias = (
        available.get(lower_timeframe, "unavailable")
        if lower_timeframe
        else "unavailable"
    )

    return CrossTimeframeAlignmentResult(
        primary_timeframe=primary,
        primary_bias=primary_bias,
        dominant_bias=dominant_bias,
        alignment_ratio=alignment_ratio,
        higher_timeframe=higher_timeframe,
        higher_bias=higher_bias,
        higher_confirmation=_confirmation_value(primary_bias, higher_bias),
        higher_state=_pair_state(primary_bias, higher_bias),
        lower_timeframe=lower_timeframe,
        lower_bias=lower_bias,
        lower_confirmation=_confirmation_value(primary_bias, lower_bias),
        lower_state=_pair_state(primary_bias, lower_bias),
        overall_state=_overall_state(dominant_bias, alignment_ratio),
        aligned_timeframes=aligned_timeframes,
        disagreeing_timeframes=disagreeing_timeframes,
        neutral_timeframes=neutral_timeframes,
    )


def _classic_bias(indicators: Mapping[str, IndicatorSnapshot]) -> str:
    score = 0.0
    for name, snapshot in indicators.items():
        state = (snapshot.state or "").upper()
        if name in {"SMA_20", "EMA_20", "VWAP"}:
            if state == "ABOVE":
                score += 1.0
            elif state == "BELOW":
                score -= 1.0
        elif name in {"RSI_14", "MFI_14"}:
            if state == "OVERSOLD":
                score += 1.0
            elif state == "OVERBOUGHT":
                score -= 1.0
        elif name == "MACD":
            if state == "BULLISH":
                score += 1.0
            elif state == "BEARISH":
                score -= 1.0

    if score > 0:
        return "bullish"
    if score < 0:
        return "bearish"
    return "neutral"


def _select_primary_timeframe(
    timeframes: tuple[TimeframeCode, ...],
) -> TimeframeCode | None:
    for timeframe in _PREFERRED_TIMEFRAMES:
        if timeframe in timeframes:
            return timeframe
    return next(iter(timeframes), None)


def _dominant_bias(non_neutral: Mapping[TimeframeCode, str]) -> str:
    bullish = sum(1 for bias in non_neutral.values() if bias == "bullish")
    bearish = sum(1 for bias in non_neutral.values() if bias == "bearish")
    if bullish > bearish:
        return "bullish"
    if bearish > bullish:
        return "bearish"
    return "neutral"


def _neighbor_timeframe(
    primary: TimeframeCode,
    *,
    direction: str,
    available: Mapping[TimeframeCode, str],
) -> TimeframeCode | None:
    index = _SCALE_ORDER.index(primary)
    if direction == "higher":
        candidates = _SCALE_ORDER[index + 1 :]
    else:
        candidates = reversed(_SCALE_ORDER[:index])
    for timeframe in candidates:
        if timeframe in available:
            return timeframe
    return None


def _confirmation_value(primary_bias: str, other_bias: str) -> float | None:
    if other_bias == "unavailable":
        return None
    if primary_bias not in {"bullish", "bearish"} or other_bias == "neutral":
        return 0.0
    if primary_bias == other_bias:
        return 1.0
    return -1.0


def _pair_state(primary_bias: str, other_bias: str) -> str:
    if other_bias == "unavailable":
        return "UNAVAILABLE"
    if primary_bias not in {"bullish", "bearish"}:
        return "NEUTRAL"
    if other_bias == "neutral":
        return "NEUTRAL"
    if primary_bias == other_bias:
        return f"CONFIRMED_{primary_bias.upper()}"
    return "DIVERGENT"


def _overall_state(dominant_bias: str, alignment_ratio: float | None) -> str:
    if dominant_bias == "neutral" or alignment_ratio is None:
        return "NEUTRAL"
    if alignment_ratio >= 1.0:
        return f"FULL_{dominant_bias.upper()}_ALIGNMENT"
    if alignment_ratio >= 0.67:
        return f"PARTIAL_{dominant_bias.upper()}_ALIGNMENT"
    return "MIXED"
