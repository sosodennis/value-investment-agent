from __future__ import annotations

from collections.abc import Mapping

from src.agents.technical.application.semantic_pipeline_contracts import (
    TechnicalEvidenceBundle,
    TechnicalProjectionArtifacts,
)
from src.agents.technical.interface.contracts import (
    EvidenceBreakoutSignalModel,
    EvidenceScorecardSummaryModel,
    QuantContextSummaryModel,
    RegimeSummaryModel,
    StructureConfluenceSummaryModel,
    VolumeProfileLevelModel,
    VolumeProfileSummaryModel,
)
from src.interface.artifacts.artifact_data_models import (
    TechnicalDirectionScorecardArtifactData,
    TechnicalFeatureIndicatorData,
    TechnicalFeaturePackArtifactData,
    TechnicalFusionReportArtifactData,
    TechnicalPatternFrameData,
    TechnicalPatternLevelData,
    TechnicalPatternPackArtifactData,
    TechnicalRegimePackArtifactData,
)


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
    breakout_signals: tuple[EvidenceBreakoutSignalModel, ...] = ()
    volume_profile_summary: VolumeProfileSummaryModel | None = None
    structure_confluence_summary: StructureConfluenceSummaryModel | None = None

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
            EvidenceBreakoutSignalModel(
                name=flag.name,
                confidence=flag.confidence,
                notes=flag.notes,
            )
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
        quant_context_summary=_build_quant_context_summary(
            feature_pack=artifacts.feature_pack,
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


def _build_regime_summary(
    *,
    regime_pack: TechnicalRegimePackArtifactData | None,
    fusion_report: TechnicalFusionReportArtifactData | None,
) -> RegimeSummaryModel | None:
    if regime_pack is not None and regime_pack.regime_summary is not None:
        return RegimeSummaryModel(
            timeframe_count=regime_pack.regime_summary.timeframe_count,
            dominant_regime=regime_pack.regime_summary.dominant_regime,
            average_confidence=regime_pack.regime_summary.average_confidence,
        )
    if fusion_report is not None and fusion_report.regime_summary is not None:
        return RegimeSummaryModel(
            timeframe_count=fusion_report.regime_summary.timeframe_count,
            dominant_regime=fusion_report.regime_summary.dominant_regime,
            average_confidence=fusion_report.regime_summary.average_confidence,
        )
    return None


def _build_scorecard_summary(
    *,
    scorecard: TechnicalDirectionScorecardArtifactData | None,
    timeframe: str | None,
) -> EvidenceScorecardSummaryModel | None:
    if scorecard is None or not scorecard.timeframes:
        return None
    scorecard_timeframe = timeframe
    if scorecard_timeframe is None or scorecard_timeframe not in scorecard.timeframes:
        scorecard_timeframe = next(iter(scorecard.timeframes), None)
    if scorecard_timeframe is None:
        return None
    frame = scorecard.timeframes[scorecard_timeframe]
    overall_score = scorecard.overall_score
    total_score = frame.total_score
    return EvidenceScorecardSummaryModel(
        timeframe=scorecard_timeframe,
        overall_score=round(float(overall_score), 2)
        if isinstance(overall_score, int | float)
        else None,
        total_score=round(float(total_score), 2)
        if isinstance(total_score, int | float)
        else None,
        classic_label=frame.classic_label,
        quant_label=frame.quant_label,
        pattern_label=frame.pattern_label,
    )


def _build_quant_context_summary(
    *,
    feature_pack: TechnicalFeaturePackArtifactData | None,
    timeframe: str | None,
) -> QuantContextSummaryModel | None:
    if feature_pack is None or not feature_pack.timeframes:
        return None
    feature_timeframe = timeframe
    if feature_timeframe is None or feature_timeframe not in feature_pack.timeframes:
        feature_timeframe = _select_preferred_timeframe(feature_pack.timeframes, None)
    if feature_timeframe is None:
        return None
    frame = feature_pack.timeframes.get(feature_timeframe)
    if frame is None or not frame.quant_features:
        return None

    payload = QuantContextSummaryModel(
        timeframe=feature_timeframe,
        volatility_regime=_indicator_state(frame.quant_features, "VOL_PERCENTILE_252"),
        liquidity_regime=_indicator_state(
            frame.quant_features, "DOLLAR_VOLUME_PERCENTILE_252"
        ),
        stretch_state=_indicator_state(frame.quant_features, "PRICE_VS_SMA20_Z"),
        alignment_state=_indicator_state(frame.quant_features, "MTF_ALIGNMENT_RATIO"),
        higher_confirmation_state=_indicator_state(
            frame.quant_features, "HTF_CONFIRMATION"
        ),
        lower_confirmation_state=_indicator_state(
            frame.quant_features, "LTF_CONFIRMATION"
        ),
        volatility_percentile=_indicator_value(
            frame.quant_features, "VOL_PERCENTILE_252"
        ),
        liquidity_percentile=_indicator_value(
            frame.quant_features, "DOLLAR_VOLUME_PERCENTILE_252"
        ),
        price_vs_sma20_z=_indicator_value(frame.quant_features, "PRICE_VS_SMA20_Z"),
        price_distance_atr=_indicator_value(
            frame.quant_features, "PRICE_DISTANCE_ATR_14"
        ),
        alignment_ratio=_indicator_value(frame.quant_features, "MTF_ALIGNMENT_RATIO"),
    )
    payload_dict = payload.model_dump(mode="json", exclude_none=True)
    return (
        payload if any(value is not None for value in payload_dict.values()) else None
    )


def _build_volume_profile_summary(
    *,
    frame: TechnicalPatternFrameData,
    timeframe: str | None,
) -> VolumeProfileSummaryModel | None:
    if frame.volume_profile_summary is not None:
        return VolumeProfileSummaryModel(
            timeframe=timeframe,
            poc=frame.volume_profile_summary.poc,
            vah=frame.volume_profile_summary.vah,
            val=frame.volume_profile_summary.val,
            profile_method=frame.volume_profile_summary.profile_method,
            profile_fidelity=frame.volume_profile_summary.profile_fidelity,
            bucket_count=frame.volume_profile_summary.bucket_count,
            value_area_coverage=frame.volume_profile_summary.value_area_coverage,
        )
    if not frame.volume_profile_levels:
        return None
    return VolumeProfileSummaryModel(
        timeframe=timeframe,
        level_count=len(frame.volume_profile_levels),
        dominant_level=_serialize_pattern_level(frame.volume_profile_levels[0]),
        levels=[
            _serialize_pattern_level(level) for level in frame.volume_profile_levels[:3]
        ],
    )


def _build_structure_confluence_summary(
    *,
    frame: TechnicalPatternFrameData,
    timeframe: str | None,
) -> StructureConfluenceSummaryModel | None:
    if frame.confluence_metadata is None:
        return None
    payload = frame.confluence_metadata.model_dump(mode="json", exclude_none=True)
    if timeframe is not None:
        payload["timeframe"] = timeframe
    return StructureConfluenceSummaryModel.model_validate(payload)


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
    pattern_pack: TechnicalPatternPackArtifactData | None,
    timeframe: str | None,
) -> tuple[str | None, TechnicalPatternFrameData | None]:
    if pattern_pack is None:
        return None, None
    timeframes = pattern_pack.timeframes
    if not timeframes:
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


def _serialize_pattern_level(
    level: TechnicalPatternLevelData,
) -> VolumeProfileLevelModel:
    return VolumeProfileLevelModel(
        price=level.price,
        strength=level.strength,
        touches=level.touches,
        label=level.label,
    )


def _indicator_state(
    indicators: Mapping[str, TechnicalFeatureIndicatorData],
    name: str,
) -> str | None:
    indicator = indicators.get(name)
    state = indicator.state if indicator is not None else None
    return state if isinstance(state, str) else None


def _indicator_value(
    indicators: Mapping[str, TechnicalFeatureIndicatorData],
    name: str,
) -> float | None:
    indicator = indicators.get(name)
    value = indicator.value if indicator is not None else None
    if isinstance(value, int | float):
        return round(float(value), 3)
    return None
