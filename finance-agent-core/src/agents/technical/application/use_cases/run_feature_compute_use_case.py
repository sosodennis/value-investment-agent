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
    build_feature_compute_error_update,
    build_feature_compute_success_update,
)
from src.agents.technical.domain.shared import PriceSeries
from src.agents.technical.interface.serializers import build_feature_compute_preview
from src.agents.technical.subdomains.features import (
    FeatureRuntimeRequest,
    FeatureRuntimeService,
    IndicatorSeriesRuntimeRequest,
    IndicatorSeriesRuntimeResult,
    IndicatorSeriesRuntimeService,
)
from src.interface.artifacts.artifact_data_models import (
    TechnicalFeaturePackArtifactData,
    TechnicalTimeseriesBundleArtifactData,
)
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject
from src.shared.kernel.workflow_contracts import WorkflowNodeResult

logger = get_logger(__name__)
TechnicalNodeResult = WorkflowNodeResult


class FeatureComputeRuntime(Protocol):
    async def load_timeseries_bundle(
        self, artifact_id: str
    ) -> TechnicalTimeseriesBundleArtifactData | None: ...

    async def save_feature_pack(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    async def save_indicator_series(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    build_progress_artifact: Callable[[str, JSONObject], dict[str, object]]


async def run_feature_compute_use_case(
    runtime: FeatureComputeRuntime,
    state: Mapping[str, object],
    *,
    feature_runtime: FeatureRuntimeService,
    indicator_series_runtime: IndicatorSeriesRuntimeService,
) -> TechnicalNodeResult:
    ticker_value = resolved_ticker_from_state(state)
    log_event(
        logger,
        event="technical_feature_compute_started",
        message="technical feature computation started",
        fields={"ticker": ticker_value},
    )

    technical_context = technical_state_from_state(state)
    input_count = 0
    timeseries_bundle_id = technical_context.timeseries_bundle_id
    if timeseries_bundle_id is None:
        log_event(
            logger,
            event="technical_feature_compute_missing_bundle_id",
            message="technical feature compute failed due to missing timeseries bundle id",
            level=logging.ERROR,
            error_code="TECHNICAL_TIMESERIES_BUNDLE_ID_MISSING",
            fields={"ticker": ticker_value},
        )
        log_event(
            logger,
            event="technical_feature_compute_completed",
            message="technical feature computation completed",
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
            update=build_feature_compute_error_update("Missing timeseries bundle ID"),
            goto="END",
        )

    try:
        bundle = await runtime.load_timeseries_bundle(timeseries_bundle_id)
        if bundle is None:
            log_event(
                logger,
                event="technical_feature_compute_bundle_not_found",
                message="technical feature compute failed due to missing timeseries bundle",
                level=logging.ERROR,
                error_code="TECHNICAL_TIMESERIES_BUNDLE_NOT_FOUND",
                fields={
                    "ticker": ticker_value,
                    "timeseries_bundle_id": timeseries_bundle_id,
                },
            )
            log_event(
                logger,
                event="technical_feature_compute_completed",
                message="technical feature computation completed",
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
                update=build_feature_compute_error_update(
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

        feature_request = FeatureRuntimeRequest(
            ticker=bundle.ticker,
            as_of=bundle.as_of,
            series_by_timeframe=series_by_timeframe,
        )
        feature_result = await asyncio.to_thread(
            feature_runtime.compute, feature_request
        )

        indicator_request = IndicatorSeriesRuntimeRequest(
            ticker=bundle.ticker,
            as_of=bundle.as_of,
            series_by_timeframe=series_by_timeframe,
        )
        indicator_result = await asyncio.to_thread(
            indicator_series_runtime.compute,
            indicator_request,
        )

        feature_pack_payload = _feature_pack_to_payload(
            feature_result.feature_pack,
            feature_result.degraded_reasons,
        )
        feature_pack_id = await runtime.save_feature_pack(
            data=feature_pack_payload,
            produced_by="technical_analysis.feature_compute",
            key_prefix=ticker_value,
        )
        indicator_series_payload = _indicator_series_to_payload(indicator_result)
        indicator_series_id = await runtime.save_indicator_series(
            data=indicator_series_payload,
            produced_by="technical_analysis.indicator_series_compute",
            key_prefix=ticker_value,
        )
    except Exception as exc:
        log_event(
            logger,
            event="technical_feature_compute_failed",
            message="technical feature computation failed",
            level=logging.ERROR,
            error_code="TECHNICAL_FEATURE_COMPUTE_FAILED",
            fields={"ticker": ticker_value, "exception": str(exc)},
        )
        log_event(
            logger,
            event="technical_feature_compute_completed",
            message="technical feature computation completed",
            level=logging.ERROR,
            fields={
                "ticker": ticker_value,
                "status": "error",
                "is_degraded": True,
                "error_code": "TECHNICAL_FEATURE_COMPUTE_FAILED",
                "input_count": input_count,
                "output_count": 0,
                "artifact_written": False,
            },
        )
        return TechnicalNodeResult(
            update=build_feature_compute_error_update(
                f"Computation crashed: {str(exc)}"
            ),
            goto="END",
        )

    feature_summary = feature_pack_payload.get("feature_summary")
    summary_dict = feature_summary if isinstance(feature_summary, dict) else {}
    preview = build_feature_compute_preview(
        ticker=ticker_value or "N/A",
        classic_count=summary_dict.get("classic_count", 0),
        quant_count=summary_dict.get("quant_count", 0),
        timeframe_count=summary_dict.get("timeframe_count", 0),
    )
    artifact = runtime.build_progress_artifact(
        f"Technical Analysis: Features computed for {ticker_value or 'N/A'}",
        preview,
    )
    combined_degraded = [
        *feature_result.degraded_reasons,
        *indicator_result.degraded_reasons,
    ]
    if combined_degraded:
        log_event(
            logger,
            event="technical_feature_compute_degraded",
            message="technical feature computation completed with degraded quality",
            level=logging.WARNING,
            error_code="TECHNICAL_FEATURE_COMPUTE_DEGRADED",
            fields={
                "ticker": ticker_value,
                "degrade_source": "feature_runtime/indicator_series_runtime",
                "fallback_mode": "continue_with_partial_features",
                "degraded_reasons": combined_degraded,
                "input_count": input_count,
                "output_count": len(feature_pack_payload.get("timeframes", {})),
            },
        )
    log_event(
        logger,
        event="technical_feature_compute_completed",
        message="technical feature computation completed",
        fields={
            "ticker": ticker_value,
            "status": "done",
            "is_degraded": bool(combined_degraded),
            "feature_pack_id": feature_pack_id,
            "indicator_series_id": indicator_series_id,
            "input_count": input_count,
            "output_count": len(feature_pack_payload.get("timeframes", {})),
            "artifact_written": True,
        },
    )

    return TechnicalNodeResult(
        update=build_feature_compute_success_update(
            feature_pack_id=feature_pack_id,
            indicator_series_id=indicator_series_id,
            artifact=artifact,
        ),
        goto="pattern_compute",
    )


def _feature_pack_to_payload(
    feature_pack: object,
    degraded_reasons: list[str],
) -> JSONObject:
    if isinstance(feature_pack, TechnicalFeaturePackArtifactData):
        payload = feature_pack.model_dump(mode="json")
        if isinstance(payload, dict):
            return payload
    if hasattr(feature_pack, "__dict__"):
        data = feature_pack.__dict__.copy()
    else:
        raise TypeError("feature_pack must be serializable")

    timeframes = data.get("timeframes", {})
    serialized_timeframes: dict[str, object] = {}
    for key, frame in timeframes.items():
        serialized_timeframes[str(key)] = {
            "classic_indicators": _serialize_indicators(
                getattr(frame, "classic_indicators", {})
            ),
            "quant_features": _serialize_indicators(
                getattr(frame, "quant_features", {})
            ),
        }

    return {
        "ticker": data.get("ticker"),
        "as_of": data.get("as_of"),
        "timeframes": serialized_timeframes,
        "feature_summary": data.get("feature_summary") or {},
        "degraded_reasons": degraded_reasons or None,
    }


def _serialize_indicators(indicators: Mapping[str, object]) -> dict[str, object]:
    serialized: dict[str, object] = {}
    for key, indicator in indicators.items():
        if hasattr(indicator, "__dict__"):
            data = indicator.__dict__
            serialized[key] = {
                "name": data.get("name"),
                "value": data.get("value"),
                "state": data.get("state"),
                "metadata": data.get("metadata") or {},
            }
        elif isinstance(indicator, dict):
            serialized[key] = indicator
    return serialized


def _indicator_series_to_payload(
    result: IndicatorSeriesRuntimeResult,
) -> JSONObject:
    timeframes_payload: dict[str, object] = {}
    for key, frame in result.timeframes.items():
        timeframes_payload[str(key)] = {
            "timeframe": frame.timeframe,
            "start": frame.start,
            "end": frame.end,
            "series": frame.series,
            "timezone": frame.timezone,
            "metadata": frame.metadata or None,
        }
    return {
        "ticker": result.ticker,
        "as_of": result.as_of,
        "timeframes": timeframes_payload,
        "degraded_reasons": result.degraded_reasons or None,
    }
