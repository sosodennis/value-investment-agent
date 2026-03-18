from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel

from src.agents.technical.application.semantic_pipeline_contracts import (
    TechnicalEvidenceBundle,
    TechnicalProjectionArtifacts,
)
from src.interface.artifacts.artifact_data_models import (
    TechnicalPatternFrameData,
    TechnicalPatternLevelData,
)
from src.shared.kernel.types import JSONObject


def build_technical_evidence_bundle(
    *,
    artifacts: TechnicalProjectionArtifacts,
) -> TechnicalEvidenceBundle:
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

    support_levels: tuple[float, ...] = ()
    resistance_levels: tuple[float, ...] = ()
    breakout_signals: tuple[JSONObject, ...] = ()
    volume_profile_summary: JSONObject | None = None
    structure_confluence_summary: JSONObject | None = None

    resolved_timeframe, pattern_frame = _select_pattern_frame(
        pattern_pack=artifacts.pattern_pack,
        timeframe=timeframe,
    )
    if pattern_frame is not None:
        support_levels = tuple(
            round(level.price, 2) for level in pattern_frame.support_levels[:2]
        )
        resistance_levels = tuple(
            round(level.price, 2) for level in pattern_frame.resistance_levels[:2]
        )
        breakout_signals = tuple(
            {
                "name": flag.name,
                "confidence": flag.confidence,
                "notes": flag.notes,
            }
            for flag in pattern_frame.breakouts[:2]
        )
        volume_profile_summary = _build_volume_profile_summary(
            frame=pattern_frame,
            timeframe=resolved_timeframe,
        )
        structure_confluence_summary = _build_structure_confluence_summary(
            frame=pattern_frame,
            timeframe=resolved_timeframe,
        )

    return TechnicalEvidenceBundle(
        primary_timeframe=timeframe,
        support_levels=support_levels,
        resistance_levels=resistance_levels,
        breakout_signals=breakout_signals,
        scorecard_summary=_build_scorecard_summary(
            scorecard=artifacts.direction_scorecard,
            timeframe=timeframe,
        ),
        regime_summary=_build_regime_summary(
            regime_pack=artifacts.regime_pack,
            fusion_report=artifacts.fusion_report,
        ),
        volume_profile_summary=volume_profile_summary,
        structure_confluence_summary=structure_confluence_summary,
        conflict_reasons=tuple(
            artifacts.fusion_report.conflict_reasons
            if artifacts.fusion_report is not None
            and artifacts.fusion_report.conflict_reasons
            else ()
        ),
    )


def build_projection_context_from_evidence(
    evidence_bundle: TechnicalEvidenceBundle | None,
) -> JSONObject:
    if evidence_bundle is None:
        return {}
    projection_context: JSONObject = {}
    if evidence_bundle.regime_summary is not None:
        projection_context["regime_summary"] = dict(evidence_bundle.regime_summary)
    if evidence_bundle.volume_profile_summary is not None:
        projection_context["volume_profile_summary"] = dict(
            evidence_bundle.volume_profile_summary
        )
    if evidence_bundle.structure_confluence_summary is not None:
        projection_context["structure_confluence_summary"] = dict(
            evidence_bundle.structure_confluence_summary
        )
    return projection_context


def serialize_evidence_bundle(
    evidence_bundle: TechnicalEvidenceBundle | None,
) -> JSONObject | None:
    if evidence_bundle is None:
        return None
    if (
        evidence_bundle.primary_timeframe is None
        and not evidence_bundle.support_levels
        and not evidence_bundle.resistance_levels
        and not evidence_bundle.breakout_signals
        and evidence_bundle.scorecard_summary is None
        and not evidence_bundle.conflict_reasons
        and evidence_bundle.regime_summary is None
        and evidence_bundle.volume_profile_summary is None
        and evidence_bundle.structure_confluence_summary is None
    ):
        return None

    payload: JSONObject = {
        "primary_timeframe": evidence_bundle.primary_timeframe,
        "support_levels": list(evidence_bundle.support_levels),
        "resistance_levels": list(evidence_bundle.resistance_levels),
        "breakout_signals": [
            dict(signal) for signal in evidence_bundle.breakout_signals
        ],
        "conflict_reasons": list(evidence_bundle.conflict_reasons),
    }
    if evidence_bundle.scorecard_summary is not None:
        payload["scorecard_summary"] = dict(evidence_bundle.scorecard_summary)
    if evidence_bundle.regime_summary is not None:
        payload["regime_summary"] = dict(evidence_bundle.regime_summary)
    if evidence_bundle.volume_profile_summary is not None:
        payload["volume_profile_summary"] = dict(evidence_bundle.volume_profile_summary)
    if evidence_bundle.structure_confluence_summary is not None:
        payload["structure_confluence_summary"] = dict(
            evidence_bundle.structure_confluence_summary
        )
    return payload


def build_setup_context_from_evidence(
    evidence_bundle: TechnicalEvidenceBundle | None,
) -> JSONObject | None:
    if evidence_bundle is None:
        return None
    if (
        evidence_bundle.primary_timeframe is None
        and not evidence_bundle.support_levels
        and not evidence_bundle.resistance_levels
        and not evidence_bundle.breakout_signals
        and evidence_bundle.scorecard_summary is None
        and not evidence_bundle.conflict_reasons
        and evidence_bundle.regime_summary is None
        and evidence_bundle.volume_profile_summary is None
        and evidence_bundle.structure_confluence_summary is None
    ):
        return None

    setup_context: JSONObject = {
        "primary_timeframe": evidence_bundle.primary_timeframe,
        "support_levels": list(evidence_bundle.support_levels),
        "resistance_levels": list(evidence_bundle.resistance_levels),
        "breakout_signals": [
            dict(signal) for signal in evidence_bundle.breakout_signals
        ],
        "scorecard_summary": (
            dict(evidence_bundle.scorecard_summary)
            if evidence_bundle.scorecard_summary is not None
            else None
        ),
        "conflict_reasons": list(evidence_bundle.conflict_reasons),
    }
    setup_context.update(build_projection_context_from_evidence(evidence_bundle))
    return setup_context


def _build_regime_summary(
    *,
    regime_pack: object,
    fusion_report: object,
) -> JSONObject | None:
    if regime_pack is not None:
        summary = getattr(regime_pack, "regime_summary", None)
        parsed = _read_optional_object(summary)
        if parsed is not None:
            return parsed
    if fusion_report is not None:
        summary = getattr(fusion_report, "regime_summary", None)
        parsed = _read_optional_object(summary)
        if parsed is not None:
            return parsed
    return None


def _build_scorecard_summary(
    *,
    scorecard: object,
    timeframe: str | None,
) -> JSONObject | None:
    if scorecard is None:
        return None
    scorecard_timeframes = getattr(scorecard, "timeframes", None)
    if not isinstance(scorecard_timeframes, Mapping) or not scorecard_timeframes:
        return None
    scorecard_timeframe = timeframe
    if scorecard_timeframe is None or scorecard_timeframe not in scorecard_timeframes:
        scorecard_timeframe = next(iter(scorecard_timeframes), None)
    if scorecard_timeframe is None:
        return None
    frame = scorecard_timeframes[scorecard_timeframe]
    overall_score = getattr(scorecard, "overall_score", None)
    total_score = getattr(frame, "total_score", None)
    return {
        "timeframe": scorecard_timeframe,
        "overall_score": round(float(overall_score), 2)
        if isinstance(overall_score, int | float)
        else None,
        "total_score": round(float(total_score), 2)
        if isinstance(total_score, int | float)
        else None,
        "classic_label": getattr(frame, "classic_label", None),
        "quant_label": getattr(frame, "quant_label", None),
        "pattern_label": getattr(frame, "pattern_label", None),
    }


def _build_volume_profile_summary(
    *,
    frame: TechnicalPatternFrameData,
    timeframe: str | None,
) -> JSONObject | None:
    if frame.volume_profile_summary is not None:
        summary = _read_optional_object(frame.volume_profile_summary)
        if summary is not None:
            if timeframe is not None and "timeframe" not in summary:
                summary["timeframe"] = timeframe
            return summary
    if not frame.volume_profile_levels:
        return None
    return {
        "timeframe": timeframe,
        "level_count": len(frame.volume_profile_levels),
        "dominant_level": _serialize_pattern_level(frame.volume_profile_levels[0]),
        "levels": [
            _serialize_pattern_level(level) for level in frame.volume_profile_levels[:3]
        ],
    }


def _build_structure_confluence_summary(
    *,
    frame: TechnicalPatternFrameData,
    timeframe: str | None,
) -> JSONObject | None:
    if frame.confluence_metadata is None:
        return None
    summary = _read_optional_object(frame.confluence_metadata) or {}
    if timeframe is not None:
        summary["timeframe"] = timeframe
    return summary


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
        return next(iter(pattern_timeframes), None)
    if scorecard_timeframes:
        return next(iter(scorecard_timeframes), None)
    return None


def _select_pattern_frame(
    *,
    pattern_pack: object,
    timeframe: str | None,
) -> tuple[str | None, TechnicalPatternFrameData | None]:
    if pattern_pack is None:
        return None, None
    timeframes = getattr(pattern_pack, "timeframes", None)
    if not isinstance(timeframes, Mapping) or not timeframes:
        return None, None
    if timeframe is not None and timeframe in timeframes:
        frame = timeframes[timeframe]
        if isinstance(frame, TechnicalPatternFrameData):
            return timeframe, frame
    fallback_timeframe = next(iter(timeframes), None)
    if fallback_timeframe is None:
        return None, None
    frame = timeframes[fallback_timeframe]
    if not isinstance(frame, TechnicalPatternFrameData):
        return None, None
    return fallback_timeframe, frame


def _serialize_pattern_level(level: TechnicalPatternLevelData) -> JSONObject:
    payload: JSONObject = {"price": level.price}
    if level.strength is not None:
        payload["strength"] = level.strength
    if level.touches is not None:
        payload["touches"] = level.touches
    if level.label is not None:
        payload["label"] = level.label
    return payload


def _read_optional_object(value: object) -> JSONObject | None:
    if isinstance(value, BaseModel):
        dumped = value.model_dump(mode="json", exclude_none=True)
        return dumped if isinstance(dumped, dict) else None
    if isinstance(value, Mapping):
        return dict(value)
    return None
