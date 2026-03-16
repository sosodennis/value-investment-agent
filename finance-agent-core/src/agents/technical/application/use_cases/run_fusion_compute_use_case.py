from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from typing import Protocol

from src.agents.technical.application.state_readers import (
    resolved_ticker_from_state,
    technical_state_from_state,
)
from src.agents.technical.application.state_updates import (
    build_fusion_compute_error_update,
    build_fusion_compute_success_update,
)
from src.agents.technical.domain.shared import (
    FeatureFrame,
    FeaturePack,
    IndicatorSnapshot,
    KeyLevel,
    PatternFlag,
    PatternFrame,
    PatternPack,
    PriceSeries,
    TimeAlignmentGuardService,
)
from src.agents.technical.interface.serializers import build_fusion_compute_preview
from src.agents.technical.subdomains.signal_fusion import (
    FusionRuntimeRequest,
    FusionRuntimeService,
)
from src.interface.artifacts.artifact_data_models import (
    TechnicalFeaturePackArtifactData,
    TechnicalFusionReportArtifactData,
    TechnicalPatternPackArtifactData,
    TechnicalTimeseriesBundleArtifactData,
)
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject
from src.shared.kernel.workflow_contracts import WorkflowNodeResult

logger = get_logger(__name__)
TechnicalNodeResult = WorkflowNodeResult


class FusionComputeRuntime(Protocol):
    async def load_timeseries_bundle(
        self, artifact_id: str
    ) -> TechnicalTimeseriesBundleArtifactData | None: ...

    async def load_feature_pack(
        self, artifact_id: str
    ) -> TechnicalFeaturePackArtifactData | None: ...

    async def load_pattern_pack(
        self, artifact_id: str
    ) -> TechnicalPatternPackArtifactData | None: ...

    async def save_fusion_report(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    build_progress_artifact: Callable[[str, JSONObject], dict[str, object]]


async def run_fusion_compute_use_case(
    runtime: FusionComputeRuntime,
    state: Mapping[str, object],
    *,
    fusion_runtime: FusionRuntimeService,
) -> TechnicalNodeResult:
    ticker_value = resolved_ticker_from_state(state)
    log_event(
        logger,
        event="technical_fusion_compute_started",
        message="technical fusion computation started",
        fields={"ticker": ticker_value},
    )

    technical_context = technical_state_from_state(state)
    feature_pack_id = technical_context.feature_pack_id
    pattern_pack_id = technical_context.pattern_pack_id
    if feature_pack_id is None or pattern_pack_id is None:
        log_event(
            logger,
            event="technical_fusion_missing_pack_id",
            message="technical fusion failed due to missing feature/pattern pack id",
            level=logging.ERROR,
            error_code="TECHNICAL_FUSION_PACK_ID_MISSING",
            fields={
                "ticker": ticker_value,
                "feature_pack_id": feature_pack_id,
                "pattern_pack_id": pattern_pack_id,
            },
        )
        log_event(
            logger,
            event="technical_fusion_compute_completed",
            message="technical fusion computation completed",
            level=logging.ERROR,
            fields={
                "ticker": ticker_value,
                "status": "error",
                "is_degraded": True,
                "error_code": "TECHNICAL_FUSION_PACK_ID_MISSING",
                "input_count": 0,
                "output_count": 0,
                "artifact_written": False,
            },
        )
        return TechnicalNodeResult(
            update=build_fusion_compute_error_update("Missing feature/pattern pack ID"),
            goto="END",
        )

    degraded_reasons: list[str] = []
    alignment_report: dict[str, object] | None = None
    alignment = None

    try:
        feature_pack_payload = await runtime.load_feature_pack(feature_pack_id)
        if feature_pack_payload is None:
            log_event(
                logger,
                event="technical_fusion_feature_pack_not_found",
                message="technical fusion failed due to missing feature pack",
                level=logging.ERROR,
                error_code="TECHNICAL_FEATURE_PACK_NOT_FOUND",
                fields={
                    "ticker": ticker_value,
                    "feature_pack_id": feature_pack_id,
                },
            )
            log_event(
                logger,
                event="technical_fusion_compute_completed",
                message="technical fusion computation completed",
                level=logging.ERROR,
                fields={
                    "ticker": ticker_value,
                    "status": "error",
                    "is_degraded": True,
                    "error_code": "TECHNICAL_FEATURE_PACK_NOT_FOUND",
                    "input_count": 0,
                    "output_count": 0,
                    "artifact_written": False,
                },
            )
            return TechnicalNodeResult(
                update=build_fusion_compute_error_update(
                    "Feature pack not found in store"
                ),
                goto="END",
            )

        pattern_pack_payload = await runtime.load_pattern_pack(pattern_pack_id)
        if pattern_pack_payload is None:
            log_event(
                logger,
                event="technical_fusion_pattern_pack_not_found",
                message="technical fusion failed due to missing pattern pack",
                level=logging.ERROR,
                error_code="TECHNICAL_PATTERN_PACK_NOT_FOUND",
                fields={
                    "ticker": ticker_value,
                    "pattern_pack_id": pattern_pack_id,
                },
            )
            log_event(
                logger,
                event="technical_fusion_compute_completed",
                message="technical fusion computation completed",
                level=logging.ERROR,
                fields={
                    "ticker": ticker_value,
                    "status": "error",
                    "is_degraded": True,
                    "error_code": "TECHNICAL_PATTERN_PACK_NOT_FOUND",
                    "input_count": 0,
                    "output_count": 0,
                    "artifact_written": False,
                },
            )
            return TechnicalNodeResult(
                update=build_fusion_compute_error_update(
                    "Pattern pack not found in store"
                ),
                goto="END",
            )

        timeseries_bundle_id = technical_context.timeseries_bundle_id
        if timeseries_bundle_id is None:
            degraded_reasons.append("ALIGNMENT_BUNDLE_MISSING")
        else:
            bundle = await runtime.load_timeseries_bundle(timeseries_bundle_id)
            if bundle is None:
                degraded_reasons.append("ALIGNMENT_BUNDLE_NOT_FOUND")
            else:
                series_by_timeframe: dict[str, PriceSeries] = {}
                for timeframe, frame in bundle.frames.items():
                    series_by_timeframe[timeframe] = PriceSeries(
                        timeframe=timeframe,
                        start=frame.start,
                        end=frame.end,
                        price_series=frame.price_series,
                        volume_series=frame.volume_series,
                        timezone=frame.timezone,
                        metadata=frame.metadata or {},
                    )

                if not series_by_timeframe:
                    degraded_reasons.append("ALIGNMENT_FRAMES_EMPTY")
                else:
                    anchor_timeframe = (
                        "1d"
                        if "1d" in series_by_timeframe
                        else next(iter(series_by_timeframe))
                    )
                    alignment = TimeAlignmentGuardService().validate(
                        anchor=anchor_timeframe,
                        frames=series_by_timeframe,
                    )
                    alignment_report = _alignment_report_to_payload(alignment)
                    if alignment.look_ahead_detected:
                        degraded_reasons.append("ALIGNMENT_LOOK_AHEAD_DETECTED")

        feature_pack = _feature_pack_from_payload(feature_pack_payload)
        pattern_pack = _pattern_pack_from_payload(pattern_pack_payload)

        fusion_request = FusionRuntimeRequest(
            ticker=feature_pack.ticker,
            as_of=feature_pack.as_of,
            feature_pack=feature_pack,
            pattern_pack=pattern_pack,
            alignment_report=alignment,
        )
        fusion_result = await asyncio.to_thread(
            fusion_runtime.compute,
            fusion_request,
        )

        degraded_reasons.extend(fusion_result.degraded_reasons)

        fusion_report_payload = _fusion_report_to_payload(
            fusion_result,
            alignment_report=alignment_report,
            feature_pack_id=feature_pack_id,
            pattern_pack_id=pattern_pack_id,
            timeseries_bundle_id=timeseries_bundle_id,
            degraded_reasons=degraded_reasons,
        )

        fusion_report_id = await runtime.save_fusion_report(
            data=fusion_report_payload,
            produced_by="technical_analysis.fusion_compute",
            key_prefix=ticker_value,
        )
    except Exception as exc:
        log_event(
            logger,
            event="technical_fusion_compute_failed",
            message="technical fusion computation failed",
            level=logging.ERROR,
            error_code="TECHNICAL_FUSION_COMPUTE_FAILED",
            fields={"ticker": ticker_value, "exception": str(exc)},
        )
        log_event(
            logger,
            event="technical_fusion_compute_completed",
            message="technical fusion computation completed",
            level=logging.ERROR,
            fields={
                "ticker": ticker_value,
                "status": "error",
                "is_degraded": True,
                "error_code": "TECHNICAL_FUSION_COMPUTE_FAILED",
                "input_count": 0,
                "output_count": 0,
                "artifact_written": False,
            },
        )
        return TechnicalNodeResult(
            update=build_fusion_compute_error_update(
                f"Computation crashed: {str(exc)}"
            ),
            goto="END",
        )

    preview = build_fusion_compute_preview(
        ticker=ticker_value or "N/A",
        direction=fusion_result.fusion_signal.direction,
        risk_level=fusion_result.fusion_signal.risk_level,
        confidence=fusion_result.fusion_signal.confidence,
    )
    artifact = runtime.build_progress_artifact(
        f"Technical Analysis: Signal fusion computed for {ticker_value or 'N/A'}",
        preview,
    )

    feature_timeframe_count = _timeframe_count_from_pack(feature_pack_payload)
    pattern_timeframe_count = _timeframe_count_from_pack(pattern_pack_payload)
    input_count = feature_timeframe_count + pattern_timeframe_count
    output_count = len(fusion_report_payload.get("confluence_matrix", {}))

    if degraded_reasons:
        log_event(
            logger,
            event="technical_fusion_compute_degraded",
            message="technical fusion computation completed with degraded quality",
            level=logging.WARNING,
            error_code="TECHNICAL_FUSION_COMPUTE_DEGRADED",
            fields={
                "ticker": ticker_value,
                "degrade_source": "fusion_runtime",
                "fallback_mode": "continue_with_partial_fusion",
                "degraded_reasons": degraded_reasons,
                "input_count": input_count,
                "output_count": output_count,
            },
        )

    log_event(
        logger,
        event="technical_fusion_compute_completed",
        message="technical fusion computation completed",
        fields={
            "ticker": ticker_value,
            "status": "done",
            "is_degraded": bool(degraded_reasons),
            "fusion_report_id": fusion_report_id,
            "input_count": input_count,
            "output_count": output_count,
            "artifact_written": True,
        },
    )

    return TechnicalNodeResult(
        update=build_fusion_compute_success_update(
            fusion_report_id=fusion_report_id,
            confidence=fusion_result.fusion_signal.confidence,
            artifact=artifact,
        ),
        goto="verification_compute",
    )


def _feature_pack_from_payload(
    payload: TechnicalFeaturePackArtifactData,
) -> FeaturePack:
    frames: dict[str, FeatureFrame] = {}
    for timeframe, frame in payload.timeframes.items():
        classic = {
            name: IndicatorSnapshot(
                name=indicator.name,
                value=indicator.value,
                state=indicator.state,
                metadata=indicator.metadata or {},
            )
            for name, indicator in frame.classic_indicators.items()
        }
        quant = {
            name: IndicatorSnapshot(
                name=indicator.name,
                value=indicator.value,
                state=indicator.state,
                metadata=indicator.metadata or {},
            )
            for name, indicator in frame.quant_features.items()
        }
        frames[timeframe] = FeatureFrame(
            classic_indicators=classic,
            quant_features=quant,
        )
    return FeaturePack(
        ticker=payload.ticker,
        as_of=payload.as_of,
        timeframes=frames,
        feature_summary=payload.feature_summary or {},
    )


def _pattern_pack_from_payload(
    payload: TechnicalPatternPackArtifactData,
) -> PatternPack:
    frames: dict[str, PatternFrame] = {}
    for timeframe, frame in payload.timeframes.items():
        support = [
            KeyLevel(
                price=level.price,
                strength=level.strength,
                touches=level.touches,
                label=level.label,
            )
            for level in frame.support_levels
        ]
        resistance = [
            KeyLevel(
                price=level.price,
                strength=level.strength,
                touches=level.touches,
                label=level.label,
            )
            for level in frame.resistance_levels
        ]
        breakouts = [
            PatternFlag(
                name=flag.name,
                confidence=flag.confidence,
                notes=flag.notes,
            )
            for flag in frame.breakouts
        ]
        trendlines = [
            PatternFlag(
                name=flag.name,
                confidence=flag.confidence,
                notes=flag.notes,
            )
            for flag in frame.trendlines
        ]
        pattern_flags = [
            PatternFlag(
                name=flag.name,
                confidence=flag.confidence,
                notes=flag.notes,
            )
            for flag in frame.pattern_flags
        ]
        frames[timeframe] = PatternFrame(
            support_levels=support,
            resistance_levels=resistance,
            breakouts=breakouts,
            trendlines=trendlines,
            pattern_flags=pattern_flags,
            confidence_scores=frame.confidence_scores or {},
        )
    return PatternPack(
        ticker=payload.ticker,
        as_of=payload.as_of,
        timeframes=frames,
        pattern_summary=payload.pattern_summary or {},
    )


def _timeframe_count_from_pack(
    payload: TechnicalFeaturePackArtifactData | TechnicalPatternPackArtifactData,
) -> int:
    timeframes = payload.timeframes or {}
    return len(timeframes)


def _alignment_report_to_payload(report: object) -> dict[str, object]:
    if hasattr(report, "__dict__"):
        return dict(report.__dict__)
    return {}


def _fusion_report_to_payload(
    result: object,
    *,
    alignment_report: dict[str, object] | None,
    feature_pack_id: str | None,
    pattern_pack_id: str | None,
    timeseries_bundle_id: str | None,
    degraded_reasons: list[str],
) -> JSONObject:
    if isinstance(result, TechnicalFusionReportArtifactData):
        payload = result.model_dump(mode="json")
        if isinstance(payload, dict):
            return payload

    fusion_result = result
    fusion_signal = fusion_result.fusion_signal
    diagnostics = fusion_signal.diagnostics

    return {
        "schema_version": "1.0",
        "ticker": fusion_signal.ticker,
        "as_of": fusion_signal.as_of,
        "direction": fusion_signal.direction,
        "risk_level": fusion_signal.risk_level,
        "confidence": fusion_signal.confidence,
        "confluence_matrix": diagnostics.confluence_matrix if diagnostics else {},
        "conflict_reasons": diagnostics.conflict_reasons if diagnostics else [],
        "alignment_report": alignment_report,
        "source_artifacts": {
            "timeseries_bundle_id": timeseries_bundle_id,
            "feature_pack_id": feature_pack_id,
            "pattern_pack_id": pattern_pack_id,
        },
        "degraded_reasons": list(degraded_reasons),
    }
