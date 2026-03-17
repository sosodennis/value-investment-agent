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
from src.agents.technical.subdomains.regime.contracts import RegimeFrame, RegimePack

Scalar = float | int | str | bool | None

_TIMEFRAME_PRIORITY: dict[str, int] = {"1wk": 0, "1d": 1, "1h": 2}
FUSION_SCORECARD_MODEL_VERSION = "ta_fusion_v1"


@dataclass(frozen=True)
class IndicatorContribution:
    name: str
    value: float | None
    state: str | None
    contribution: float
    weight: float | None = None
    notes: str | None = None


@dataclass(frozen=True)
class ScorecardFrame:
    timeframe: TimeframeCode
    base_total_score: float
    classic_score: float
    quant_score: float
    pattern_score: float
    total_score: float
    classic_label: str
    quant_label: str
    pattern_label: str
    regime: str | None = None
    regime_directional_bias: str | None = None
    regime_weight_multiplier: float | None = None
    regime_notes: list[str] = field(default_factory=list)
    contributions: dict[str, list[IndicatorContribution]] = field(default_factory=dict)


@dataclass(frozen=True)
class DirectionScorecard:
    ticker: str
    as_of: str
    direction: str
    risk_level: str
    confidence: float | None
    neutral_threshold: float
    overall_score: float
    model_version: str
    timeframes: dict[TimeframeCode, ScorecardFrame]
    regime_summary: dict[str, Scalar] = field(default_factory=dict)
    conflict_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FusionRuntimeRequest:
    ticker: str
    as_of: str
    feature_pack: FeaturePack
    pattern_pack: PatternPack
    regime_pack: RegimePack | None = None
    alignment_report: AlignmentReport | None = None


@dataclass(frozen=True)
class FusionRuntimeResult:
    fusion_signal: FusionSignal
    degraded_reasons: list[str] = field(default_factory=list)
    scorecard: DirectionScorecard | None = None


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
        regime_risk_levels: list[str] = []

        scorecard_frames: dict[TimeframeCode, ScorecardFrame] = {}
        for timeframe in timeframes:
            feature_frame = feature_pack.timeframes.get(timeframe)
            pattern_frame = pattern_pack.timeframes.get(timeframe)
            regime_frame = (
                request.regime_pack.timeframes.get(timeframe)
                if request.regime_pack is not None
                else None
            )
            if feature_frame is None:
                degraded.append(f"{timeframe}_FEATURE_FRAME_MISSING")
                continue
            if pattern_frame is None:
                degraded.append(f"{timeframe}_PATTERN_FRAME_MISSING")
                pattern_frame = PatternFrame()
            if request.regime_pack is not None and regime_frame is None:
                degraded.append(f"{timeframe}_REGIME_FRAME_MISSING")

            classic_score, classic_contribs = _score_classic(
                feature_frame.classic_indicators
            )
            quant_score, quant_extreme, stat_strength, quant_contribs = _score_quant(
                feature_frame.quant_features
            )
            pattern_score, pattern_contribs = _score_pattern(pattern_frame)
            base_total_score = classic_score + quant_score + pattern_score

            base_classic_label = _label_score(classic_score, self.neutral_threshold)
            base_quant_label = _label_score(quant_score, self.neutral_threshold)
            base_pattern_label = _label_score(pattern_score, self.neutral_threshold)
            regime_adjustment = _apply_regime_adjustment(
                timeframe=timeframe,
                classic_score=classic_score,
                quant_score=quant_score,
                pattern_score=pattern_score,
                classic_label=base_classic_label,
                quant_label=base_quant_label,
                pattern_label=base_pattern_label,
                regime_frame=regime_frame,
            )
            classic_score = regime_adjustment.classic_score
            quant_score = regime_adjustment.quant_score
            pattern_score = regime_adjustment.pattern_score

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
            conflict_reasons.extend(regime_adjustment.conflict_reasons)
            if regime_adjustment.risk_level is not None:
                regime_risk_levels.append(regime_adjustment.risk_level)

            confluence_matrix[timeframe] = {
                "classic": classic_label,
                "quant": quant_label,
                "pattern": pattern_label,
                "classic_score": round(classic_score, 3),
                "quant_score": round(quant_score, 3),
                "pattern_score": round(pattern_score, 3),
                "regime": regime_frame.regime if regime_frame is not None else None,
                "regime_bias": (
                    regime_frame.directional_bias if regime_frame is not None else None
                ),
                "regime_multiplier": regime_adjustment.weight_multiplier,
                "regime_notes": list(regime_adjustment.notes),
            }
            total_score = classic_score + quant_score + pattern_score
            timeframe_scores.append(total_score)

            scorecard_frames[timeframe] = ScorecardFrame(
                timeframe=timeframe,
                base_total_score=round(base_total_score, 3),
                classic_score=round(classic_score, 3),
                quant_score=round(quant_score, 3),
                pattern_score=round(pattern_score, 3),
                total_score=round(total_score, 3),
                classic_label=classic_label,
                quant_label=quant_label,
                pattern_label=pattern_label,
                regime=regime_frame.regime if regime_frame is not None else None,
                regime_directional_bias=(
                    regime_frame.directional_bias if regime_frame is not None else None
                ),
                regime_weight_multiplier=regime_adjustment.weight_multiplier,
                regime_notes=list(regime_adjustment.notes),
                contributions={
                    "classic": classic_contribs,
                    "quant": quant_contribs,
                    "pattern": pattern_contribs,
                },
            )

        if not timeframes:
            degraded.append("FUSION_NO_TIMEFRAMES")

        overall_score = _average(timeframe_scores)
        direction = _direction_from_score(overall_score, self.neutral_threshold)
        confidence = _estimate_confidence(timeframe_scores, stat_strengths)
        risk_level = _risk_level(
            extreme_detected=extreme_detected,
            conflict_reasons=conflict_reasons,
            regime_risk_levels=regime_risk_levels,
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

        scorecard = DirectionScorecard(
            ticker=request.ticker,
            as_of=request.as_of,
            direction=direction,
            risk_level=risk_level,
            confidence=confidence,
            neutral_threshold=self.neutral_threshold,
            overall_score=round(overall_score, 3),
            model_version=FUSION_SCORECARD_MODEL_VERSION,
            regime_summary=(
                dict(request.regime_pack.regime_summary)
                if request.regime_pack is not None
                else {}
            ),
            timeframes=scorecard_frames,
            conflict_reasons=conflict_reasons,
        )

        return FusionRuntimeResult(
            fusion_signal=fusion_signal,
            degraded_reasons=degraded,
            scorecard=scorecard,
        )


@dataclass(frozen=True)
class RegimeAdjustment:
    classic_score: float
    quant_score: float
    pattern_score: float
    weight_multiplier: float | None = None
    notes: tuple[str, ...] = ()
    conflict_reasons: tuple[str, ...] = ()
    risk_level: str | None = None


def _sorted_timeframes(timeframes: set[TimeframeCode]) -> list[TimeframeCode]:
    return sorted(timeframes, key=lambda tf: _TIMEFRAME_PRIORITY.get(tf, 99))


def _apply_regime_adjustment(
    *,
    timeframe: TimeframeCode,
    classic_score: float,
    quant_score: float,
    pattern_score: float,
    classic_label: str,
    quant_label: str,
    pattern_label: str,
    regime_frame: RegimeFrame | None,
) -> RegimeAdjustment:
    if regime_frame is None:
        return RegimeAdjustment(
            classic_score=classic_score,
            quant_score=quant_score,
            pattern_score=pattern_score,
        )

    notes = [
        f"regime={regime_frame.regime}",
        f"bias={regime_frame.directional_bias}",
    ]
    conflict_reasons: list[str] = []
    classic_multiplier = 1.0
    quant_multiplier = 1.0
    pattern_multiplier = 1.0
    risk_level: str | None = None

    if regime_frame.regime == "BULL_TREND":
        classic_multiplier = _trend_multiplier(classic_label, expected="bullish")
        quant_multiplier = _trend_multiplier(quant_label, expected="bullish")
        pattern_multiplier = _trend_multiplier(pattern_label, expected="bullish")
        conflict_reasons.extend(
            _regime_label_conflicts(
                timeframe=timeframe,
                expected="bullish",
                classic_label=classic_label,
                quant_label=quant_label,
                pattern_label=pattern_label,
            )
        )
        notes.append("trend_following_bias")
    elif regime_frame.regime == "BEAR_TREND":
        classic_multiplier = _trend_multiplier(classic_label, expected="bearish")
        quant_multiplier = _trend_multiplier(quant_label, expected="bearish")
        pattern_multiplier = _trend_multiplier(pattern_label, expected="bearish")
        conflict_reasons.extend(
            _regime_label_conflicts(
                timeframe=timeframe,
                expected="bearish",
                classic_label=classic_label,
                quant_label=quant_label,
                pattern_label=pattern_label,
            )
        )
        notes.append("trend_following_bias")
    elif regime_frame.regime == "HIGH_VOL_CHOP":
        classic_multiplier = 0.85
        quant_multiplier = 0.8
        pattern_multiplier = 0.7
        risk_level = "medium"
        notes.append("volatility_penalty")
        if any(
            label != "neutral" for label in (classic_label, quant_label, pattern_label)
        ):
            conflict_reasons.append(f"{timeframe}:REGIME_HIGH_VOL_CHOP_DAMPENS_SIGNALS")
    elif regime_frame.regime == "QUIET_MEAN_REVERSION":
        classic_multiplier = 0.9
        quant_multiplier = 0.95
        pattern_multiplier = 1.1
        notes.append("quiet_mean_reversion_bias")

    adjusted_classic = classic_score * classic_multiplier
    adjusted_quant = quant_score * quant_multiplier
    adjusted_pattern = pattern_score * pattern_multiplier
    average_multiplier = round(
        (classic_multiplier + quant_multiplier + pattern_multiplier) / 3.0, 3
    )
    return RegimeAdjustment(
        classic_score=adjusted_classic,
        quant_score=adjusted_quant,
        pattern_score=adjusted_pattern,
        weight_multiplier=average_multiplier,
        notes=tuple(notes),
        conflict_reasons=tuple(conflict_reasons),
        risk_level=risk_level,
    )


def _trend_multiplier(label: str, *, expected: str) -> float:
    if label == expected:
        return 1.2
    if label == "neutral":
        return 1.0
    return 0.75


def _regime_label_conflicts(
    *,
    timeframe: TimeframeCode,
    expected: str,
    classic_label: str,
    quant_label: str,
    pattern_label: str,
) -> list[str]:
    conflicts: list[str] = []
    for category, label in (
        ("CLASSIC", classic_label),
        ("QUANT", quant_label),
        ("PATTERN", pattern_label),
    ):
        if label != "neutral" and label != expected:
            conflicts.append(
                f"{timeframe}:REGIME_{expected.upper()}_VS_{category}_{label.upper()}"
            )
    return conflicts


def _score_classic(
    indicators: dict[str, IndicatorSnapshot],
) -> tuple[float, list[IndicatorContribution]]:
    score = 0.0
    contributions: list[IndicatorContribution] = []
    for name in sorted(indicators):
        snapshot = indicators[name]
        state = (snapshot.state or "").upper()
        contribution = 0.0
        if name in {"SMA_20", "EMA_20", "VWAP"}:
            if state == "ABOVE":
                contribution = 1.0
            elif state == "BELOW":
                contribution = -1.0
        elif name in {"RSI_14", "MFI_14"}:
            if state == "OVERSOLD":
                contribution = 1.0
            elif state == "OVERBOUGHT":
                contribution = -1.0
        elif name == "MACD":
            if state == "BULLISH":
                contribution = 1.0
            elif state == "BEARISH":
                contribution = -1.0

        score += contribution
        contributions.append(
            IndicatorContribution(
                name=snapshot.name,
                value=snapshot.value,
                state=snapshot.state,
                contribution=round(contribution, 3),
                notes=_metadata_note(snapshot),
            )
        )
    return score, contributions


def _score_quant(
    indicators: dict[str, IndicatorSnapshot],
) -> tuple[float, bool, float | None, list[IndicatorContribution]]:
    score = 0.0
    extreme = False
    stat_strength: float | None = None
    contributions: list[IndicatorContribution] = []

    for name in sorted(indicators):
        snapshot = indicators[name]
        state = (snapshot.state or "").upper()
        contribution = 0.0

        if name == "FD_Z_SCORE" and snapshot.value is not None:
            z_val = float(snapshot.value)
            if z_val >= 0.5:
                contribution = 1.0
            elif z_val <= -0.5:
                contribution = -1.0
            if abs(z_val) >= 2.0:
                extreme = True

        elif name == "FD_OBV_Z":
            if state in {"ACCUMULATION_ANOMALY", "MILD_ACCUMULATION"}:
                contribution = 0.5
            elif state in {"DISTRIBUTION_ANOMALY", "MILD_DISTRIBUTION"}:
                contribution = -0.5

        elif name == "FD_BOLLINGER_BW":
            if state == "BREAKOUT_UPPER":
                contribution = 0.25
            elif state == "BREAKOUT_LOWER":
                contribution = -0.25

        elif name == "FD_STAT_STRENGTH" and snapshot.value is not None:
            stat_strength = float(snapshot.value)

        score += contribution
        contributions.append(
            IndicatorContribution(
                name=snapshot.name,
                value=snapshot.value,
                state=snapshot.state,
                contribution=round(contribution, 3),
                notes=_metadata_note(snapshot),
            )
        )

    return score, extreme, stat_strength, contributions


def _score_pattern(
    frame: PatternFrame,
) -> tuple[float, list[IndicatorContribution]]:
    score = 0.0
    contributions: list[IndicatorContribution] = []

    for flag in frame.breakouts:
        name = flag.name.upper()
        contribution = 0.0
        if name == "BREAKOUT_UP":
            contribution = 1.0
        elif name == "BREAKOUT_DOWN":
            contribution = -1.0
        score += contribution
        contributions.append(
            IndicatorContribution(
                name=flag.name,
                value=flag.confidence,
                state=None,
                contribution=round(contribution, 3),
                notes=flag.notes,
            )
        )

    for flag in frame.trendlines:
        name = flag.name.upper()
        contribution = 0.0
        if name == "UPTREND":
            contribution = 0.5
        elif name == "DOWNTREND":
            contribution = -0.5
        score += contribution
        contributions.append(
            IndicatorContribution(
                name=flag.name,
                value=flag.confidence,
                state=None,
                contribution=round(contribution, 3),
                notes=flag.notes,
            )
        )

    for flag in frame.pattern_flags:
        name = flag.name.upper()
        contribution = 0.0
        if name == "NEAR_SUPPORT":
            contribution = 0.25
        elif name == "NEAR_RESISTANCE":
            contribution = -0.25
        score += contribution
        contributions.append(
            IndicatorContribution(
                name=flag.name,
                value=flag.confidence,
                state=None,
                contribution=round(contribution, 3),
                notes=flag.notes,
            )
        )

    return score, contributions


def _metadata_note(snapshot: IndicatorSnapshot) -> str | None:
    metadata = snapshot.metadata or {}
    reason = metadata.get("reason")
    if isinstance(reason, str) and reason.strip():
        return reason
    return None


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


def _risk_level(
    *,
    extreme_detected: bool,
    conflict_reasons: list[str],
    regime_risk_levels: list[str],
) -> str:
    if extreme_detected:
        return "critical"

    risk_level = "low"
    if conflict_reasons:
        risk_level = "medium"

    for level in regime_risk_levels:
        if _risk_rank(level) > _risk_rank(risk_level):
            risk_level = level
    return risk_level


def _risk_rank(level: str) -> int:
    mapping = {"low": 0, "medium": 1, "critical": 2}
    return mapping.get(level, 0)
