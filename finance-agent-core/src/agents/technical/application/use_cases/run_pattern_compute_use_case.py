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
    build_pattern_compute_error_update,
    build_pattern_compute_success_update,
)
from src.agents.technical.domain.shared import (
    KeyLevel,
    PatternFlag,
    PatternFrame,
    PriceSeries,
)
from src.agents.technical.interface.serializers import build_pattern_compute_preview
from src.agents.technical.subdomains.patterns import (
    PatternRuntimeRequest,
    PatternRuntimeService,
)
from src.interface.artifacts.artifact_data_models import (
    TechnicalPatternPackArtifactData,
    TechnicalTimeseriesBundleArtifactData,
)
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject
from src.shared.kernel.workflow_contracts import WorkflowNodeResult

logger = get_logger(__name__)
TechnicalNodeResult = WorkflowNodeResult


class PatternComputeRuntime(Protocol):
    async def load_timeseries_bundle(
        self, artifact_id: str
    ) -> TechnicalTimeseriesBundleArtifactData | None: ...

    async def save_pattern_pack(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    build_progress_artifact: Callable[[str, JSONObject], dict[str, object]]


async def run_pattern_compute_use_case(
    runtime: PatternComputeRuntime,
    state: Mapping[str, object],
    *,
    pattern_runtime: PatternRuntimeService,
) -> TechnicalNodeResult:
    ticker_value = resolved_ticker_from_state(state)
    log_event(
        logger,
        event="technical_pattern_compute_started",
        message="technical pattern computation started",
        fields={"ticker": ticker_value},
    )

    technical_context = technical_state_from_state(state)
    input_count = 0
    timeseries_bundle_id = technical_context.timeseries_bundle_id
    if timeseries_bundle_id is None:
        log_event(
            logger,
            event="technical_pattern_compute_missing_bundle_id",
            message="technical pattern compute failed due to missing timeseries bundle id",
            level=logging.ERROR,
            error_code="TECHNICAL_TIMESERIES_BUNDLE_ID_MISSING",
            fields={"ticker": ticker_value},
        )
        log_event(
            logger,
            event="technical_pattern_compute_completed",
            message="technical pattern computation completed",
            level=logging.ERROR,
            fields={
                "ticker": ticker_value,
                "status": "error",
                "is_degraded": True,
                "error_code": "TECHNICAL_TIMESERIES_BUNDLE_ID_MISSING",
                "input_count": input_count,
                "output_count": 0,
                "artifact_written": False,
            },
        )
        return TechnicalNodeResult(
            update=build_pattern_compute_error_update("Missing timeseries bundle ID"),
            goto="END",
        )

    try:
        bundle = await runtime.load_timeseries_bundle(timeseries_bundle_id)
        if bundle is None:
            log_event(
                logger,
                event="technical_pattern_compute_bundle_not_found",
                message="technical pattern compute failed due to missing timeseries bundle",
                level=logging.ERROR,
                error_code="TECHNICAL_TIMESERIES_BUNDLE_NOT_FOUND",
                fields={
                    "ticker": ticker_value,
                    "timeseries_bundle_id": timeseries_bundle_id,
                },
            )
            log_event(
                logger,
                event="technical_pattern_compute_completed",
                message="technical pattern computation completed",
                level=logging.ERROR,
                fields={
                    "ticker": ticker_value,
                    "status": "error",
                    "is_degraded": True,
                    "error_code": "TECHNICAL_TIMESERIES_BUNDLE_NOT_FOUND",
                    "input_count": input_count,
                    "output_count": 0,
                    "artifact_written": False,
                },
            )
            return TechnicalNodeResult(
                update=build_pattern_compute_error_update(
                    "Timeseries bundle not found in store"
                ),
                goto="END",
            )

        series_by_timeframe: dict[str, PriceSeries] = {}
        for timeframe, frame in bundle.frames.items():
            series_by_timeframe[timeframe] = PriceSeries(
                timeframe=timeframe,
                start=frame.start,
                end=frame.end,
                price_series=frame.price_series,
                volume_series=frame.volume_series,
                open_series=frame.open_series,
                high_series=frame.high_series,
                low_series=frame.low_series,
                close_series=frame.close_series,
                timezone=frame.timezone,
                metadata=frame.metadata or {},
            )
        input_count = len(series_by_timeframe)

        pattern_request = PatternRuntimeRequest(
            ticker=bundle.ticker,
            as_of=bundle.as_of,
            series_by_timeframe=series_by_timeframe,
        )
        pattern_result = await asyncio.to_thread(
            pattern_runtime.compute,
            pattern_request,
        )

        pattern_pack_payload = _pattern_pack_to_payload(
            pattern_result.pattern_pack,
            pattern_result.degraded_reasons,
        )
        pattern_pack_id = await runtime.save_pattern_pack(
            data=pattern_pack_payload,
            produced_by="technical_analysis.pattern_compute",
            key_prefix=ticker_value,
        )
    except Exception as exc:
        log_event(
            logger,
            event="technical_pattern_compute_failed",
            message="technical pattern computation failed",
            level=logging.ERROR,
            error_code="TECHNICAL_PATTERN_COMPUTE_FAILED",
            fields={"ticker": ticker_value, "exception": str(exc)},
        )
        log_event(
            logger,
            event="technical_pattern_compute_completed",
            message="technical pattern computation completed",
            level=logging.ERROR,
            fields={
                "ticker": ticker_value,
                "status": "error",
                "is_degraded": True,
                "error_code": "TECHNICAL_PATTERN_COMPUTE_FAILED",
                "input_count": input_count,
                "output_count": 0,
                "artifact_written": False,
            },
        )
        return TechnicalNodeResult(
            update=build_pattern_compute_error_update(
                f"Computation crashed: {str(exc)}"
            ),
            goto="END",
        )

    summary = pattern_pack_payload.get("pattern_summary")
    summary_dict = summary if isinstance(summary, dict) else {}
    preview = build_pattern_compute_preview(
        ticker=ticker_value or "N/A",
        support_count=summary_dict.get("support_level_count", 0),
        resistance_count=summary_dict.get("resistance_level_count", 0),
        breakout_count=summary_dict.get("breakout_count", 0),
    )
    artifact = runtime.build_progress_artifact(
        f"Technical Analysis: Patterns computed for {ticker_value or 'N/A'}",
        preview,
    )

    if pattern_result.degraded_reasons:
        log_event(
            logger,
            event="technical_pattern_compute_degraded",
            message="technical pattern computation completed with degraded quality",
            level=logging.WARNING,
            error_code="TECHNICAL_PATTERN_COMPUTE_DEGRADED",
            fields={
                "ticker": ticker_value,
                "degrade_source": "pattern_runtime",
                "fallback_mode": "continue_with_partial_patterns",
                "degraded_reasons": pattern_result.degraded_reasons,
                "input_count": input_count,
                "output_count": len(pattern_pack_payload.get("timeframes", {})),
            },
        )

    log_event(
        logger,
        event="technical_pattern_compute_completed",
        message="technical pattern computation completed",
        fields={
            "ticker": ticker_value,
            "status": "done",
            "is_degraded": bool(pattern_result.degraded_reasons),
            "pattern_pack_id": pattern_pack_id,
            "input_count": input_count,
            "output_count": len(pattern_pack_payload.get("timeframes", {})),
            "artifact_written": True,
        },
    )

    return TechnicalNodeResult(
        update=build_pattern_compute_success_update(
            pattern_pack_id=pattern_pack_id,
            artifact=artifact,
        ),
        goto="alerts_compute",
    )


def _pattern_pack_to_payload(
    pattern_pack: object,
    degraded_reasons: list[str],
) -> JSONObject:
    if isinstance(pattern_pack, TechnicalPatternPackArtifactData):
        payload = pattern_pack.model_dump(mode="json")
        if isinstance(payload, dict):
            return payload
    if hasattr(pattern_pack, "__dict__"):
        data = pattern_pack.__dict__.copy()
    else:
        raise TypeError("pattern_pack must be serializable")

    timeframes = data.get("timeframes", {})
    serialized_timeframes: dict[str, object] = {}
    for key, frame in timeframes.items():
        serialized_timeframes[str(key)] = _serialize_pattern_frame(frame)

    return {
        "ticker": data.get("ticker"),
        "as_of": data.get("as_of"),
        "timeframes": serialized_timeframes,
        "pattern_summary": data.get("pattern_summary"),
        "degraded_reasons": degraded_reasons,
    }


def _serialize_pattern_frame(frame: PatternFrame) -> dict[str, object]:
    return {
        "support_levels": _serialize_levels(frame.support_levels),
        "resistance_levels": _serialize_levels(frame.resistance_levels),
        "volume_profile_levels": _serialize_levels(frame.volume_profile_levels),
        "volume_profile_summary": _serialize_volume_profile_summary(
            frame.volume_profile_summary
        ),
        "breakouts": _serialize_flags(frame.breakouts),
        "trendlines": _serialize_flags(frame.trendlines),
        "pattern_flags": _serialize_flags(frame.pattern_flags),
        "confluence_metadata": frame.confluence_metadata,
        "confidence_scores": frame.confidence_scores,
    }


def _serialize_levels(levels: list[KeyLevel]) -> list[dict[str, object]]:
    return [
        {
            "price": level.price,
            "strength": level.strength,
            "touches": level.touches,
            "label": level.label,
        }
        for level in levels
    ]


def _serialize_flags(flags: list[PatternFlag]) -> list[dict[str, object]]:
    return [
        {
            "name": flag.name,
            "confidence": flag.confidence,
            "notes": flag.notes,
        }
        for flag in flags
    ]


def _serialize_volume_profile_summary(summary: object) -> dict[str, object] | None:
    if summary is None:
        return None
    if hasattr(summary, "__dict__"):
        return dict(summary.__dict__)
    raise TypeError("volume_profile_summary must be serializable")
