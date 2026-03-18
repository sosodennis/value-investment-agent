from __future__ import annotations

import asyncio
from collections.abc import Mapping

from src.agents.technical.application.ports import TechnicalInterpretationInput
from src.agents.technical.application.semantic_pipeline_contracts import (
    BacktestContextResult,
    TechnicalPortLike,
    TechnicalProjectionArtifacts,
)
from src.agents.technical.application.signal_explainer_context_service import (
    build_signal_explainer_context,
)
from src.agents.technical.subdomains.signal_fusion import SemanticTagPolicyResult
from src.interface.artifacts.artifact_data_models import (
    TechnicalDirectionScorecardArtifactData,
    TechnicalFusionReportArtifactData,
    TechnicalPatternFrameData,
    TechnicalPatternLevelData,
    TechnicalPatternPackArtifactData,
    TechnicalRegimePackArtifactData,
)
from src.shared.kernel.types import JSONObject


async def build_interpretation_input(
    *,
    ticker: str,
    technical_context: JSONObject,
    tags_result: SemanticTagPolicyResult,
    backtest_context_result: BacktestContextResult,
    technical_port: TechnicalPortLike,
    projection_artifacts: TechnicalProjectionArtifacts | None = None,
) -> TechnicalInterpretationInput:
    artifacts = projection_artifacts or await load_projection_artifacts(
        technical_context=technical_context,
        technical_port=technical_port,
    )
    projection_context = build_projection_context(artifacts=artifacts)

    confidence_raw = technical_context.get("confidence_calibrated")
    confidence = (
        float(confidence_raw) if isinstance(confidence_raw, int | float) else None
    )
    return TechnicalInterpretationInput(
        ticker=ticker,
        direction=tags_result.direction,
        risk_level=tags_result.risk_level,
        confidence=confidence,
        confidence_calibrated=confidence,
        summary_tags=tuple(tags_result.tags),
        evidence_items=tuple(tags_result.evidence_list),
        momentum_extremes=_read_optional_object(
            technical_context.get("momentum_extremes")
        ),
        setup_context=_build_setup_context(
            pattern_pack=artifacts.pattern_pack,
            scorecard=artifacts.direction_scorecard,
            fusion_report=artifacts.fusion_report,
            projection_context=projection_context,
        ),
        validation_context=_build_validation_context(backtest_context_result),
        diagnostics_context=_build_diagnostics_context(
            technical_context=technical_context,
            fusion_report=artifacts.fusion_report,
        ),
        signal_explainer_context=build_signal_explainer_context(artifacts.feature_pack),
    )


async def load_projection_artifacts(
    *,
    technical_context: JSONObject,
    technical_port: TechnicalPortLike,
) -> TechnicalProjectionArtifacts:
    feature_pack_id = _read_optional_text(technical_context.get("feature_pack_id"))
    pattern_pack_id = _read_optional_text(technical_context.get("pattern_pack_id"))
    regime_pack_id = _read_optional_text(technical_context.get("regime_pack_id"))
    fusion_report_id = _read_optional_text(technical_context.get("fusion_report_id"))
    direction_scorecard_id = _read_optional_text(
        technical_context.get("direction_scorecard_id")
    )
    (
        feature_pack,
        pattern_pack,
        regime_pack,
        fusion_report,
        direction_scorecard,
    ) = await asyncio.gather(
        technical_port.load_feature_pack(feature_pack_id),
        technical_port.load_pattern_pack(pattern_pack_id),
        technical_port.load_regime_pack(regime_pack_id),
        technical_port.load_fusion_report(fusion_report_id),
        technical_port.load_direction_scorecard(direction_scorecard_id),
    )
    return TechnicalProjectionArtifacts(
        feature_pack=feature_pack,
        pattern_pack=pattern_pack,
        regime_pack=regime_pack,
        fusion_report=fusion_report,
        direction_scorecard=direction_scorecard,
    )


def build_projection_context(
    *,
    artifacts: TechnicalProjectionArtifacts,
) -> JSONObject:
    timeframe = _select_preferred_timeframe(
        artifacts.pattern_pack.timeframes
        if artifacts.pattern_pack is not None
        else None,
        (
            artifacts.direction_scorecard.timeframes
            if artifacts.direction_scorecard is not None
            else None
        ),
    )
    projection_context: JSONObject = {}
    regime_summary = _build_regime_summary(
        regime_pack=artifacts.regime_pack,
        fusion_report=artifacts.fusion_report,
    )
    if regime_summary is not None:
        projection_context["regime_summary"] = regime_summary

    volume_profile_summary = _build_volume_profile_summary(
        pattern_pack=artifacts.pattern_pack,
        timeframe=timeframe,
    )
    if volume_profile_summary is not None:
        projection_context["volume_profile_summary"] = volume_profile_summary

    structure_confluence_summary = _build_structure_confluence_summary(
        pattern_pack=artifacts.pattern_pack,
        timeframe=timeframe,
    )
    if structure_confluence_summary is not None:
        projection_context["structure_confluence_summary"] = (
            structure_confluence_summary
        )
    return projection_context


def _build_setup_context(
    *,
    pattern_pack: TechnicalPatternPackArtifactData | None,
    scorecard: TechnicalDirectionScorecardArtifactData | None,
    fusion_report: TechnicalFusionReportArtifactData | None,
    projection_context: JSONObject,
) -> JSONObject | None:
    timeframe = _select_preferred_timeframe(
        pattern_pack.timeframes if pattern_pack is not None else None,
        scorecard.timeframes if scorecard is not None else None,
    )

    support_levels: list[float] = []
    resistance_levels: list[float] = []
    breakout_signals: list[dict[str, object]] = []
    if (
        pattern_pack is not None
        and timeframe is not None
        and timeframe in pattern_pack.timeframes
    ):
        frame = pattern_pack.timeframes[timeframe]
        support_levels = [round(level.price, 2) for level in frame.support_levels[:2]]
        resistance_levels = [
            round(level.price, 2) for level in frame.resistance_levels[:2]
        ]
        breakout_signals = [
            {
                "name": flag.name,
                "confidence": flag.confidence,
                "notes": flag.notes,
            }
            for flag in frame.breakouts[:2]
        ]

    scorecard_summary: JSONObject | None = None
    if scorecard is not None:
        scorecard_timeframe = timeframe
        if (
            scorecard_timeframe is None
            or scorecard_timeframe not in scorecard.timeframes
        ):
            scorecard_timeframe = next(iter(scorecard.timeframes), None)
        if scorecard_timeframe is not None:
            frame = scorecard.timeframes[scorecard_timeframe]
            scorecard_summary = {
                "timeframe": scorecard_timeframe,
                "overall_score": round(scorecard.overall_score, 2),
                "total_score": round(frame.total_score, 2),
                "classic_label": frame.classic_label,
                "quant_label": frame.quant_label,
                "pattern_label": frame.pattern_label,
            }

    conflict_reasons = []
    if fusion_report is not None and fusion_report.conflict_reasons:
        conflict_reasons = list(fusion_report.conflict_reasons)

    if (
        timeframe is None
        and not support_levels
        and not resistance_levels
        and not breakout_signals
        and scorecard_summary is None
        and not conflict_reasons
        and not projection_context
    ):
        return None

    setup_context: JSONObject = {
        "primary_timeframe": timeframe,
        "support_levels": support_levels,
        "resistance_levels": resistance_levels,
        "breakout_signals": breakout_signals,
        "scorecard_summary": scorecard_summary,
        "conflict_reasons": conflict_reasons,
    }
    setup_context.update(projection_context)
    return setup_context


def _build_validation_context(
    backtest_context_result: BacktestContextResult,
) -> JSONObject | None:
    report = backtest_context_result.verification_report
    if (
        report is None
        and not backtest_context_result.backtest_context
        and not backtest_context_result.wfa_context
    ):
        return None
    baseline_status = None
    baseline_gates = None
    robustness_flags: list[str] = []
    degraded_reasons: list[str] = []
    if report is not None:
        baseline_gates = (
            dict(report.baseline_gates)
            if isinstance(report.baseline_gates, Mapping)
            else None
        )
        if baseline_gates is not None:
            status = baseline_gates.get("status")
            baseline_status = str(status) if isinstance(status, str) else None
        robustness_flags = list(report.robustness_flags or [])
        degraded_reasons = list(report.degraded_reasons or [])
    return {
        "backtest_summary": backtest_context_result.backtest_context or None,
        "wfa_summary": backtest_context_result.wfa_context or None,
        "baseline_status": baseline_status,
        "baseline_gates": baseline_gates,
        "robustness_flags": robustness_flags,
        "degraded_reasons": degraded_reasons,
        "is_degraded": backtest_context_result.is_degraded,
    }


def _build_diagnostics_context(
    *,
    technical_context: JSONObject,
    fusion_report: TechnicalFusionReportArtifactData | None,
) -> JSONObject | None:
    degraded_reasons = technical_context.get("degraded_reasons")
    diagnostics_reasons = (
        list(degraded_reasons) if isinstance(degraded_reasons, list) else []
    )
    calibration = _read_optional_object(technical_context.get("confidence_calibration"))
    fusion_conflicts = (
        list(fusion_report.conflict_reasons)
        if fusion_report is not None and fusion_report.conflict_reasons
        else []
    )
    if not diagnostics_reasons and calibration is None and not fusion_conflicts:
        return None
    return {
        "degraded_reasons": diagnostics_reasons,
        "confidence_calibration": calibration,
        "fusion_conflicts": fusion_conflicts,
    }


def _select_preferred_timeframe(
    pattern_timeframes: Mapping[str, object] | None,
    scorecard_timeframes: Mapping[str, object] | None,
) -> str | None:
    preferred = ("1d", "1wk", "1h")
    for timeframe in preferred:
        if pattern_timeframes is not None and timeframe in pattern_timeframes:
            return timeframe
        if scorecard_timeframes is not None and timeframe in scorecard_timeframes:
            return timeframe
    if pattern_timeframes:
        return next(iter(pattern_timeframes))
    if scorecard_timeframes:
        return next(iter(scorecard_timeframes))
    return None


def _build_regime_summary(
    *,
    regime_pack: TechnicalRegimePackArtifactData | None,
    fusion_report: TechnicalFusionReportArtifactData | None,
) -> JSONObject | None:
    if regime_pack is not None and regime_pack.regime_summary:
        return dict(regime_pack.regime_summary)
    if fusion_report is not None and fusion_report.regime_summary:
        return dict(fusion_report.regime_summary)
    return None


def _build_volume_profile_summary(
    *,
    pattern_pack: TechnicalPatternPackArtifactData | None,
    timeframe: str | None,
) -> JSONObject | None:
    resolved_timeframe, frame = _select_pattern_frame(
        pattern_pack=pattern_pack,
        timeframe=timeframe,
    )
    if frame is None:
        return None
    if frame.volume_profile_summary is not None:
        return frame.volume_profile_summary.model_dump(mode="json")
    if not frame.volume_profile_levels:
        return None
    return {
        "timeframe": resolved_timeframe,
        "level_count": len(frame.volume_profile_levels),
        "dominant_level": _serialize_pattern_level(frame.volume_profile_levels[0]),
        "levels": [
            _serialize_pattern_level(level) for level in frame.volume_profile_levels[:3]
        ],
    }


def _build_structure_confluence_summary(
    *,
    pattern_pack: TechnicalPatternPackArtifactData | None,
    timeframe: str | None,
) -> JSONObject | None:
    resolved_timeframe, frame = _select_pattern_frame(
        pattern_pack=pattern_pack,
        timeframe=timeframe,
    )
    if frame is None or frame.confluence_metadata is None:
        return None
    summary: JSONObject = {"timeframe": resolved_timeframe}
    for key, value in frame.confluence_metadata.items():
        summary[str(key)] = value
    return summary


def _select_pattern_frame(
    *,
    pattern_pack: TechnicalPatternPackArtifactData | None,
    timeframe: str | None,
) -> tuple[str | None, TechnicalPatternFrameData | None]:
    if pattern_pack is None or not pattern_pack.timeframes:
        return None, None
    if timeframe is not None and timeframe in pattern_pack.timeframes:
        return timeframe, pattern_pack.timeframes[timeframe]
    fallback_timeframe = next(iter(pattern_pack.timeframes), None)
    if fallback_timeframe is None:
        return None, None
    return fallback_timeframe, pattern_pack.timeframes[fallback_timeframe]


def _serialize_pattern_level(level: TechnicalPatternLevelData) -> JSONObject:
    payload: JSONObject = {"price": level.price}
    if level.strength is not None:
        payload["strength"] = level.strength
    if level.touches is not None:
        payload["touches"] = level.touches
    if level.label is not None:
        payload["label"] = level.label
    return payload


def _read_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _read_optional_object(value: object) -> JSONObject | None:
    if not isinstance(value, Mapping):
        return None
    return dict(value)
