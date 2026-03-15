from __future__ import annotations

from dataclasses import dataclass, field

from src.agents.technical.domain.shared import (
    AlignmentReport,
    FeaturePack,
    FusionDiagnostics,
    FusionSignal,
    IndicatorSnapshot,
    PatternFrame,
    PatternPack,
    TimeframeCode,
)

Scalar = float | int | str | bool | None

_TIMEFRAME_PRIORITY: dict[str, int] = {"1wk": 0, "1d": 1, "1h": 2}


@dataclass(frozen=True)
class FusionRuntimeRequest:
    ticker: str
    as_of: str
    feature_pack: FeaturePack
    pattern_pack: PatternPack
    alignment_report: AlignmentReport | None = None


@dataclass(frozen=True)
class FusionRuntimeResult:
    fusion_signal: FusionSignal
    degraded_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FusionRuntimeService:
    neutral_threshold: float = 0.5

    def compute(self, request: FusionRuntimeRequest) -> FusionRuntimeResult:
        feature_pack = request.feature_pack
        pattern_pack = request.pattern_pack

        timeframes = _sorted_timeframes(
            set(feature_pack.timeframes.keys()) | set(pattern_pack.timeframes.keys())
        )

        degraded: list[str] = []
        confluence_matrix: dict[str, dict[str, Scalar]] = {}
        conflict_reasons: list[str] = []
        timeframe_scores: list[float] = []
        stat_strengths: list[float] = []
        extreme_detected = False

        for timeframe in timeframes:
            feature_frame = feature_pack.timeframes.get(timeframe)
            pattern_frame = pattern_pack.timeframes.get(timeframe)
            if feature_frame is None:
                degraded.append(f"{timeframe}_FEATURE_FRAME_MISSING")
                continue
            if pattern_frame is None:
                degraded.append(f"{timeframe}_PATTERN_FRAME_MISSING")
                pattern_frame = PatternFrame()

            classic_score = _score_classic(feature_frame.classic_indicators)
            quant_score, quant_extreme, stat_strength = _score_quant(
                feature_frame.quant_features
            )
            pattern_score = _score_pattern(pattern_frame)

            extreme_detected = extreme_detected or quant_extreme
            if stat_strength is not None:
                stat_strengths.append(stat_strength)

            classic_label = _label_score(classic_score, self.neutral_threshold)
            quant_label = _label_score(quant_score, self.neutral_threshold)
            pattern_label = _label_score(pattern_score, self.neutral_threshold)

            _append_conflicts(
                conflict_reasons,
                timeframe=timeframe,
                classic_label=classic_label,
                quant_label=quant_label,
                pattern_label=pattern_label,
            )

            confluence_matrix[timeframe] = {
                "classic": classic_label,
                "quant": quant_label,
                "pattern": pattern_label,
                "classic_score": round(classic_score, 3),
                "quant_score": round(quant_score, 3),
                "pattern_score": round(pattern_score, 3),
            }
            timeframe_scores.append(classic_score + quant_score + pattern_score)

        if not timeframes:
            degraded.append("FUSION_NO_TIMEFRAMES")

        overall_score = _average(timeframe_scores)
        direction = _direction_from_score(overall_score, self.neutral_threshold)
        confidence = _estimate_confidence(timeframe_scores, stat_strengths)
        risk_level = _risk_level(
            extreme_detected=extreme_detected,
            conflict_reasons=conflict_reasons,
        )

        diagnostics = FusionDiagnostics(
            confluence_matrix=confluence_matrix,
            conflict_reasons=conflict_reasons,
            alignment_report_id=None,
            notes=[],
        )
        if request.alignment_report is not None:
            diagnostics = FusionDiagnostics(
                confluence_matrix=confluence_matrix,
                conflict_reasons=conflict_reasons,
                alignment_report_id="INLINE",
                notes=[
                    "alignment_report_included",
                    f"alignment_anchor={request.alignment_report.anchor_timeframe}",
                ],
            )

        fusion_signal = FusionSignal(
            ticker=request.ticker,
            as_of=request.as_of,
            direction=direction,
            risk_level=risk_level,
            confidence=confidence,
            diagnostics=diagnostics,
        )

        return FusionRuntimeResult(
            fusion_signal=fusion_signal, degraded_reasons=degraded
        )


def _sorted_timeframes(timeframes: set[TimeframeCode]) -> list[TimeframeCode]:
    return sorted(timeframes, key=lambda tf: _TIMEFRAME_PRIORITY.get(tf, 99))


def _score_classic(indicators: dict[str, IndicatorSnapshot]) -> float:
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
    return score


def _score_quant(
    indicators: dict[str, IndicatorSnapshot],
) -> tuple[float, bool, float | None]:
    score = 0.0
    extreme = False
    stat_strength: float | None = None

    z_snapshot = indicators.get("FD_Z_SCORE")
    if z_snapshot is not None and z_snapshot.value is not None:
        z_val = float(z_snapshot.value)
        if z_val >= 0.5:
            score += 1.0
        elif z_val <= -0.5:
            score -= 1.0
        if abs(z_val) >= 2.0:
            extreme = True

    obv_snapshot = indicators.get("FD_OBV_Z")
    if obv_snapshot is not None:
        state = (obv_snapshot.state or "").upper()
        if state in {"ACCUMULATION_ANOMALY", "MILD_ACCUMULATION"}:
            score += 0.5
        elif state in {"DISTRIBUTION_ANOMALY", "MILD_DISTRIBUTION"}:
            score -= 0.5

    boll_snapshot = indicators.get("FD_BOLLINGER_BW")
    if boll_snapshot is not None:
        state = (boll_snapshot.state or "").upper()
        if state == "BREAKOUT_UPPER":
            score += 0.25
        elif state == "BREAKOUT_LOWER":
            score -= 0.25

    stat_snapshot = indicators.get("FD_STAT_STRENGTH")
    if stat_snapshot is not None and stat_snapshot.value is not None:
        stat_strength = float(stat_snapshot.value)

    return score, extreme, stat_strength


def _score_pattern(frame: PatternFrame) -> float:
    score = 0.0
    for flag in frame.breakouts:
        name = flag.name.upper()
        if name == "BREAKOUT_UP":
            score += 1.0
        elif name == "BREAKOUT_DOWN":
            score -= 1.0

    for flag in frame.trendlines:
        name = flag.name.upper()
        if name == "UPTREND":
            score += 0.5
        elif name == "DOWNTREND":
            score -= 0.5

    for flag in frame.pattern_flags:
        name = flag.name.upper()
        if name == "NEAR_SUPPORT":
            score += 0.25
        elif name == "NEAR_RESISTANCE":
            score -= 0.25

    return score


def _label_score(score: float, threshold: float) -> str:
    if score >= threshold:
        return "bullish"
    if score <= -threshold:
        return "bearish"
    return "neutral"


def _append_conflicts(
    conflict_reasons: list[str],
    *,
    timeframe: TimeframeCode,
    classic_label: str,
    quant_label: str,
    pattern_label: str,
) -> None:
    if (
        classic_label != "neutral"
        and quant_label != "neutral"
        and classic_label != quant_label
    ):
        conflict_reasons.append(
            f"{timeframe}:CLASSIC_{classic_label.upper()}_VS_QUANT_{quant_label.upper()}"
        )
    if (
        classic_label != "neutral"
        and pattern_label != "neutral"
        and classic_label != pattern_label
    ):
        conflict_reasons.append(
            f"{timeframe}:CLASSIC_{classic_label.upper()}_VS_PATTERN_{pattern_label.upper()}"
        )
    if (
        quant_label != "neutral"
        and pattern_label != "neutral"
        and quant_label != pattern_label
    ):
        conflict_reasons.append(
            f"{timeframe}:QUANT_{quant_label.upper()}_VS_PATTERN_{pattern_label.upper()}"
        )


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _direction_from_score(score: float, threshold: float) -> str:
    if score >= threshold:
        return "BULLISH_EXTENSION"
    if score <= -threshold:
        return "BEARISH_EXTENSION"
    return "NEUTRAL_CONSOLIDATION"


def _estimate_confidence(
    scores: list[float],
    stat_strengths: list[float],
) -> float | None:
    if not scores and not stat_strengths:
        return None

    magnitude = 0.0
    if scores:
        magnitude = sum(min(1.0, abs(score) / 3.0) for score in scores) / len(scores)

    if stat_strengths:
        stat_boost = max(stat_strengths) / 100.0
        magnitude = min(1.0, magnitude + 0.2 * stat_boost)

    return round(magnitude, 2)


def _risk_level(*, extreme_detected: bool, conflict_reasons: list[str]) -> str:
    if extreme_detected:
        return "critical"
    if conflict_reasons:
        return "medium"
    return "low"
