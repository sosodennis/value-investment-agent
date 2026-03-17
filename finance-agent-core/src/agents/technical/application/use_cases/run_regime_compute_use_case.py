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
    build_regime_compute_error_update,
    build_regime_compute_success_update,
)
from src.agents.technical.domain.shared import PriceSeries
from src.agents.technical.interface.serializers import build_regime_compute_preview
from src.agents.technical.subdomains.regime import (
    RegimeRuntimeRequest,
    RegimeRuntimeService,
)
from src.interface.artifacts.artifact_data_models import (
    TechnicalFeaturePackArtifactData,
    TechnicalIndicatorSeriesArtifactData,
    TechnicalRegimePackArtifactData,
    TechnicalTimeseriesBundleArtifactData,
    TechnicalTimeseriesFrameData,
)
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject
from src.shared.kernel.workflow_contracts import WorkflowNodeResult

logger = get_logger(__name__)
TechnicalNodeResult = WorkflowNodeResult


class RegimeComputeRuntime(Protocol):
    async def load_timeseries_bundle(
        self, artifact_id: str
    ) -> TechnicalTimeseriesBundleArtifactData | None: ...

    async def load_feature_pack(
        self, artifact_id: str | None
    ) -> TechnicalFeaturePackArtifactData | None: ...

    async def load_indicator_series(
        self, artifact_id: str | None
    ) -> TechnicalIndicatorSeriesArtifactData | None: ...

    async def save_regime_pack(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    build_progress_artifact: Callable[[str, JSONObject], dict[str, object]]


async def run_regime_compute_use_case(
    runtime: RegimeComputeRuntime,
    state: Mapping[str, object],
    *,
    regime_runtime: RegimeRuntimeService,
) -> TechnicalNodeResult:
    ticker_value = resolved_ticker_from_state(state)
    log_event(
        logger,
        event="technical_regime_compute_started",
        message="technical regime computation started",
        fields={"ticker": ticker_value},
    )

    technical_context = technical_state_from_state(state)
    input_count = 0
    timeseries_bundle_id = technical_context.timeseries_bundle_id
    if timeseries_bundle_id is None:
        log_event(
            logger,
            event="technical_regime_compute_missing_bundle_id",
            message="technical regime compute failed due to missing timeseries bundle id",
            level=logging.ERROR,
            error_code="TECHNICAL_TIMESERIES_BUNDLE_ID_MISSING",
            fields={"ticker": ticker_value},
        )
        log_event(
            logger,
            event="technical_regime_compute_completed",
            message="technical regime computation completed",
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
            update=build_regime_compute_error_update("Missing timeseries bundle ID"),
            goto="END",
        )

    try:
        bundle = await runtime.load_timeseries_bundle(timeseries_bundle_id)
        if bundle is None:
            log_event(
                logger,
                event="technical_regime_compute_bundle_not_found",
                message="technical regime compute failed due to missing timeseries bundle",
                level=logging.ERROR,
                error_code="TECHNICAL_TIMESERIES_BUNDLE_NOT_FOUND",
                fields={
                    "ticker": ticker_value,
                    "timeseries_bundle_id": timeseries_bundle_id,
                },
            )
            log_event(
                logger,
                event="technical_regime_compute_completed",
                message="technical regime computation completed",
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
                update=build_regime_compute_error_update(
                    "Timeseries bundle not found in store"
                ),
                goto="END",
            )

        series_by_timeframe: dict[str, PriceSeries] = {}
        feature_pack = await runtime.load_feature_pack(
            technical_context.feature_pack_id
        )
        indicator_series = await runtime.load_indicator_series(
            technical_context.indicator_series_id
        )
        canonical_input_degraded: list[str] = []
        feature_pack, feature_pack_degraded = _validated_feature_pack(
            feature_pack,
            bundle=bundle,
        )
        indicator_series, indicator_series_degraded = _validated_indicator_series(
            indicator_series,
            bundle=bundle,
        )
        canonical_input_degraded.extend(feature_pack_degraded)
        canonical_input_degraded.extend(indicator_series_degraded)
        for timeframe, frame in bundle.frames.items():
            series_by_timeframe[timeframe], timeframe_degraded = (
                _build_regime_price_series(
                    timeframe=timeframe,
                    frame=frame,
                    feature_pack=feature_pack,
                    indicator_series=indicator_series,
                )
            )
            canonical_input_degraded.extend(
                [f"{timeframe}_{reason}" for reason in timeframe_degraded]
            )
        input_count = len(series_by_timeframe)

        regime_request = RegimeRuntimeRequest(
            ticker=bundle.ticker,
            as_of=bundle.as_of,
            series_by_timeframe=series_by_timeframe,
        )
        regime_result = await asyncio.to_thread(
            regime_runtime.compute,
            regime_request,
        )
        degraded_reasons = _merge_degraded_reasons(
            canonical_input_degraded,
            list(regime_result.degraded_reasons),
        )

        regime_pack_payload = _regime_pack_to_payload(
            regime_result.regime_pack,
            degraded_reasons,
        )
        regime_pack_id = await runtime.save_regime_pack(
            data=regime_pack_payload,
            produced_by="technical_analysis.regime_compute",
            key_prefix=ticker_value,
        )
    except Exception as exc:
        log_event(
            logger,
            event="technical_regime_compute_failed",
            message="technical regime computation failed",
            level=logging.ERROR,
            error_code="TECHNICAL_REGIME_COMPUTE_FAILED",
            fields={"ticker": ticker_value, "exception": str(exc)},
        )
        log_event(
            logger,
            event="technical_regime_compute_completed",
            message="technical regime computation completed",
            level=logging.ERROR,
            fields={
                "ticker": ticker_value,
                "status": "error",
                "is_degraded": True,
                "error_code": "TECHNICAL_REGIME_COMPUTE_FAILED",
                "input_count": input_count,
                "output_count": 0,
                "artifact_written": False,
            },
        )
        return TechnicalNodeResult(
            update=build_regime_compute_error_update(
                f"Computation crashed: {str(exc)}"
            ),
            goto="END",
        )

    summary = regime_pack_payload.get("regime_summary")
    summary_dict = summary if isinstance(summary, dict) else {}
    preview = build_regime_compute_preview(
        ticker=ticker_value or "N/A",
        dominant_regime=summary_dict.get("dominant_regime"),
        timeframe_count=summary_dict.get("timeframe_count", 0),
        degraded_count=len(degraded_reasons),
    )
    artifact = runtime.build_progress_artifact(
        f"Technical Analysis: Regime computed for {ticker_value or 'N/A'}",
        preview,
    )

    if degraded_reasons:
        log_event(
            logger,
            event="technical_regime_compute_degraded",
            message="technical regime computation completed with degraded quality",
            level=logging.WARNING,
            error_code="TECHNICAL_REGIME_COMPUTE_DEGRADED",
            fields={
                "ticker": ticker_value,
                "degrade_source": "canonical_inputs/regime_runtime",
                "fallback_mode": "continue_with_partial_regime",
                "degraded_reasons": degraded_reasons,
                "input_count": input_count,
                "output_count": len(regime_pack_payload.get("timeframes", {})),
            },
        )

    log_event(
        logger,
        event="technical_regime_compute_completed",
        message="technical regime computation completed",
        fields={
            "ticker": ticker_value,
            "status": "done",
            "is_degraded": bool(degraded_reasons),
            "regime_pack_id": regime_pack_id,
            "input_count": input_count,
            "output_count": len(regime_pack_payload.get("timeframes", {})),
            "artifact_written": True,
        },
    )

    return TechnicalNodeResult(
        update=build_regime_compute_success_update(
            regime_pack_id=regime_pack_id,
            artifact=artifact,
        ),
        goto="fusion_compute",
    )


def _regime_pack_to_payload(
    regime_pack: object,
    degraded_reasons: list[str],
) -> JSONObject:
    if isinstance(regime_pack, TechnicalRegimePackArtifactData):
        payload = regime_pack.model_dump(mode="json")
        if isinstance(payload, dict):
            payload["degraded_reasons"] = degraded_reasons or None
            return payload
    if hasattr(regime_pack, "__dict__"):
        data = regime_pack.__dict__.copy()
    else:
        raise TypeError("regime_pack must be serializable")

    timeframes = data.get("timeframes", {})
    serialized_timeframes: dict[str, object] = {}
    for key, frame in timeframes.items():
        serialized_timeframes[str(key)] = _serialize_regime_frame(frame)

    return {
        "ticker": data.get("ticker"),
        "as_of": data.get("as_of"),
        "timeframes": serialized_timeframes,
        "regime_summary": data.get("regime_summary") or {},
        "degraded_reasons": degraded_reasons or None,
    }


REGIME_INPUT_METADATA_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("ATR_14", "regime_input_atr_14", "regime_input_source_atr_14"),
    ("ATRP_14", "regime_input_atrp_14", "regime_input_source_atrp_14"),
    ("ADX_14", "regime_input_adx_14", "regime_input_source_adx_14"),
    (
        "BB_BANDWIDTH_20",
        "regime_input_bb_bandwidth_20",
        "regime_input_source_bb_bandwidth_20",
    ),
)

REGIME_FEATURE_PACK_CONTEXT_MISMATCH = "REGIME_FEATURE_PACK_CONTEXT_MISMATCH"
REGIME_INDICATOR_SERIES_CONTEXT_MISMATCH = "REGIME_INDICATOR_SERIES_CONTEXT_MISMATCH"


def _build_regime_price_series(
    *,
    timeframe: str,
    frame: TechnicalTimeseriesFrameData,
    feature_pack: TechnicalFeaturePackArtifactData | None,
    indicator_series: TechnicalIndicatorSeriesArtifactData | None,
) -> tuple[PriceSeries, list[str]]:
    metadata = dict(frame.metadata or {})
    degraded_reasons: list[str] = []
    feature_frame = feature_pack.timeframes.get(timeframe) if feature_pack else None
    indicator_frame = (
        indicator_series.timeframes.get(timeframe) if indicator_series else None
    )

    for indicator_name, value_key, source_key in REGIME_INPUT_METADATA_FIELDS:
        value, source = _resolve_regime_input(
            indicator_name=indicator_name,
            feature_frame=feature_frame,
            indicator_frame=indicator_frame,
        )
        metadata[source_key] = source
        if value is not None:
            metadata[value_key] = value
        if source == "timeseries_compute":
            degraded_reasons.append(f"REGIME_INPUT_{indicator_name}_TIMESERIES_COMPUTE")

    return (
        PriceSeries(
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
            metadata=metadata,
        ),
        degraded_reasons,
    )


def _validated_feature_pack(
    feature_pack: TechnicalFeaturePackArtifactData | None,
    *,
    bundle: TechnicalTimeseriesBundleArtifactData,
) -> tuple[TechnicalFeaturePackArtifactData | None, list[str]]:
    if feature_pack is None:
        return None, []
    if _artifact_matches_bundle(
        artifact_ticker=feature_pack.ticker,
        artifact_as_of=feature_pack.as_of,
        bundle=bundle,
    ):
        return feature_pack, []
    return None, [REGIME_FEATURE_PACK_CONTEXT_MISMATCH]


def _validated_indicator_series(
    indicator_series: TechnicalIndicatorSeriesArtifactData | None,
    *,
    bundle: TechnicalTimeseriesBundleArtifactData,
) -> tuple[TechnicalIndicatorSeriesArtifactData | None, list[str]]:
    if indicator_series is None:
        return None, []
    if _artifact_matches_bundle(
        artifact_ticker=indicator_series.ticker,
        artifact_as_of=indicator_series.as_of,
        bundle=bundle,
    ):
        return indicator_series, []
    return None, [REGIME_INDICATOR_SERIES_CONTEXT_MISMATCH]


def _artifact_matches_bundle(
    *,
    artifact_ticker: str | None,
    artifact_as_of: str | None,
    bundle: TechnicalTimeseriesBundleArtifactData,
) -> bool:
    return artifact_ticker == bundle.ticker and artifact_as_of == bundle.as_of


def _resolve_regime_input(
    *,
    indicator_name: str,
    feature_frame: object | None,
    indicator_frame: object | None,
) -> tuple[float | None, str]:
    feature_value = _feature_indicator_value(feature_frame, indicator_name)
    if feature_value is not None:
        return feature_value, "feature_pack"

    series_value = _indicator_series_value(indicator_frame, indicator_name)
    if series_value is not None:
        return series_value, "indicator_series"

    return None, "timeseries_compute"


def _feature_indicator_value(
    feature_frame: object | None,
    indicator_name: str,
) -> float | None:
    if feature_frame is None:
        return None
    classic_indicators = getattr(feature_frame, "classic_indicators", None)
    if not isinstance(classic_indicators, dict):
        return None
    indicator = classic_indicators.get(indicator_name)
    if indicator is None:
        return None
    value = getattr(indicator, "value", None)
    return _safe_float(value)


def _indicator_series_value(
    indicator_frame: object | None,
    indicator_name: str,
) -> float | None:
    if indicator_frame is None:
        return None
    series_map = getattr(indicator_frame, "series", None)
    if not isinstance(series_map, dict):
        return None
    series = series_map.get(indicator_name)
    if not isinstance(series, dict):
        return None
    keys = list(series.keys())
    for key in reversed(keys):
        value = _safe_float(series.get(key))
        if value is not None:
            return value
    return None


def _safe_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, int | float):
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _merge_degraded_reasons(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for reason in group:
            if not reason or reason in seen:
                continue
            seen.add(reason)
            merged.append(reason)
    return merged


def _serialize_regime_frame(frame: object) -> JSONObject:
    if hasattr(frame, "model_dump"):
        payload = frame.model_dump(mode="json")
        if isinstance(payload, dict):
            return payload
    if hasattr(frame, "__dict__"):
        data = frame.__dict__.copy()
        return {
            "timeframe": data.get("timeframe"),
            "regime": data.get("regime"),
            "confidence": data.get("confidence"),
            "directional_bias": data.get("directional_bias"),
            "adx": data.get("adx"),
            "atr_value": data.get("atr_value"),
            "atrp_value": data.get("atrp_value"),
            "bollinger_bandwidth": data.get("bollinger_bandwidth"),
            "evidence": list(data.get("evidence") or []),
            "metadata": data.get("metadata"),
        }
    raise TypeError("regime frame must be serializable")
