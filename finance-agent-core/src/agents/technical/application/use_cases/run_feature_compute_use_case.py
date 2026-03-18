from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable, Mapping
from dataclasses import asdict, is_dataclass
from typing import Protocol

from src.agents.technical.application.state_readers import (
    resolved_ticker_from_state,
    technical_state_from_state,
)
from src.agents.technical.application.state_updates import (
    build_feature_compute_error_update,
    build_feature_compute_success_update,
)
from src.agents.technical.domain.shared import FeatureSummary, PriceSeries
from src.agents.technical.interface.serializers import build_feature_compute_preview
from src.agents.technical.subdomains.features import (
    FeatureRuntimeRequest,
    FeatureRuntimeService,
    IndicatorSeriesFrameResult,
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
    combined_degraded = _merge_degraded_reasons(
        feature_result.degraded_reasons,
        indicator_result.degraded_reasons,
    )
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
            momentum_extremes=_build_momentum_extremes_snapshot(indicator_result),
            is_degraded=bool(combined_degraded),
            degraded_reasons=combined_degraded,
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
        "feature_summary": _serialize_feature_summary(data.get("feature_summary")),
        "degraded_reasons": degraded_reasons or None,
    }


def _serialize_indicators(indicators: Mapping[str, object]) -> dict[str, object]:
    serialized: dict[str, object] = {}
    for key, indicator in indicators.items():
        if hasattr(indicator, "__dict__"):
            data = indicator.__dict__
            provenance = data.get("provenance")
            quality = data.get("quality")
            serialized[key] = {
                "name": data.get("name"),
                "value": data.get("value"),
                "state": data.get("state"),
                "provenance": _serialize_dataclass_like(provenance),
                "quality": _serialize_dataclass_like(quality),
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
            "metadata": _serialize_dataclass_like(frame.metadata) or None,
        }
    return {
        "ticker": result.ticker,
        "as_of": result.as_of,
        "timeframes": timeframes_payload,
        "degraded_reasons": result.degraded_reasons or None,
    }


def _merge_degraded_reasons(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for reason in group:
            if reason not in merged:
                merged.append(reason)
    return merged


def _serialize_dataclass_like(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if is_dataclass(value):
        payload = asdict(value)
        quality_flags = payload.get("quality_flags")
        if isinstance(quality_flags, tuple):
            payload["quality_flags"] = list(quality_flags)
        return payload
    if isinstance(value, Mapping):
        return dict(value)
    return None


def _serialize_feature_summary(value: object) -> dict[str, object]:
    if isinstance(value, FeatureSummary):
        payload = asdict(value)
        for key in (
            "ready_timeframes",
            "degraded_timeframes",
            "regime_inputs_ready_timeframes",
        ):
            entry = payload.get(key)
            if isinstance(entry, tuple):
                payload[key] = list(entry)
        return payload
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _build_momentum_extremes_snapshot(
    result: IndicatorSeriesRuntimeResult,
) -> dict[str, object] | None:
    timeframe = _select_momentum_timeframe(result.timeframes)
    if timeframe is None:
        return None
    frame = result.timeframes.get(timeframe)
    if frame is None or not isinstance(frame.series, dict):
        return None
    rsi_value = _latest_numeric_value(frame.series.get("RSI_14"))
    fd_value = _latest_numeric_value(frame.series.get("FD_ZSCORE"))
    if rsi_value is None and fd_value is None:
        return None
    return {
        "timeframe": timeframe,
        "source": "indicator_series",
        "rsi_value": rsi_value,
        "rsi_bias": _resolve_rsi_bias(rsi_value),
        "fd_z_score": fd_value,
        "fd_label": _resolve_fd_label(fd_value),
        "fd_polarity": _resolve_fd_polarity(fd_value),
        "fd_risk_hint": _resolve_fd_risk_hint(fd_value),
    }


def _select_momentum_timeframe(
    frames: Mapping[str, IndicatorSeriesFrameResult],
) -> str | None:
    preferred = ("1d", "1wk", "1h")
    for timeframe in preferred:
        if timeframe in frames:
            return timeframe
    return next(iter(frames), None)


def _latest_numeric_value(series: Mapping[str, float | None] | None) -> float | None:
    if not series:
        return None
    keys = list(series.keys())
    for key in reversed(keys):
        value = series.get(key)
        if isinstance(value, int | float) and math.isfinite(value):
            return float(value)
    return None


def _resolve_rsi_bias(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "NO_DATA"
    if value >= 70:
        return "OVERBOUGHT"
    if value <= 30:
        return "OVERSOLD"
    if value >= 55:
        return "BULLISH_BIAS"
    if value <= 45:
        return "BEARISH_BIAS"
    return "NEUTRAL"


def _resolve_fd_label(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "NO_DATA"
    if value >= 2 or value <= -2:
        return "EXTREME"
    if value >= 1 or value <= -1:
        return "ELEVATED"
    return "BALANCED"


def _resolve_fd_polarity(value: float | None) -> str | None:
    if value is None or not math.isfinite(value):
        return None
    if value > 0:
        return "POSITIVE"
    if value < 0:
        return "NEGATIVE"
    return "NEUTRAL"


def _resolve_fd_risk_hint(value: float | None) -> str:
    label = _resolve_fd_label(value)
    if label in {"EXTREME", "ELEVATED"}:
        return "MEAN_REVERSION_RISK"
    if label == "NO_DATA":
        return "NO_DATA"
    return "NORMAL"
