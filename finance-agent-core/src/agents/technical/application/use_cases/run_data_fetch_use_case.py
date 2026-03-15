from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Protocol

import pandas as pd

from src.agents.technical.application.state_readers import resolved_ticker_from_state
from src.agents.technical.application.state_updates import (
    build_data_fetch_error_update,
    build_data_fetch_success_update,
)
from src.agents.technical.interface.serializers import build_data_fetch_preview
from src.agents.technical.subdomains.market_data.application.multi_timeframe_fetch_service import (
    MultiTimeframeFetchRequest,
    fetch_timeseries_bundle,
)
from src.agents.technical.subdomains.market_data.application.ports import (
    IMarketDataProvider,
)
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject
from src.shared.kernel.workflow_contracts import WorkflowNodeResult

logger = get_logger(__name__)
TechnicalNodeResult = WorkflowNodeResult


class DataFetchRuntime(Protocol):
    async def save_price_series(
        self,
        *,
        data: JSONObject,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    async def save_timeseries_bundle(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    build_progress_artifact: Callable[[str, JSONObject], dict[str, object]]


async def run_data_fetch_use_case(
    runtime: DataFetchRuntime,
    state: Mapping[str, object],
    *,
    market_data_provider: IMarketDataProvider,
) -> TechnicalNodeResult:
    resolved_ticker = resolved_ticker_from_state(state)
    log_event(
        logger,
        event="technical_data_fetch_started",
        message="technical data fetch started",
        fields={"ticker": resolved_ticker},
    )
    if resolved_ticker is None:
        log_event(
            logger,
            event="technical_data_fetch_missing_ticker",
            message="technical data fetch skipped due to missing resolved ticker",
            level=logging.ERROR,
            error_code="TECHNICAL_TICKER_MISSING",
        )
        log_event(
            logger,
            event="technical_data_fetch_completed",
            message="technical data fetch completed",
            level=logging.ERROR,
            fields={
                "ticker": resolved_ticker,
                "status": "error",
                "is_degraded": True,
                "error_code": "TECHNICAL_TICKER_MISSING",
                "rows": 0,
                "input_count": 0,
                "output_count": 0,
                "artifact_written": False,
            },
        )
        return TechnicalNodeResult(
            update=build_data_fetch_error_update("No resolved ticker available"),
            goto="END",
        )

    try:
        bundle_request = MultiTimeframeFetchRequest(
            ticker=resolved_ticker,
            timeframes=["1d", "1wk", "1h"],
            period="5y",
        )
        bundle_result = await asyncio.to_thread(
            fetch_timeseries_bundle, market_data_provider, bundle_request
        )
    except Exception as exc:
        log_event(
            logger,
            event="technical_data_fetch_failed",
            message="technical data fetch failed",
            level=logging.ERROR,
            error_code="TECHNICAL_DATA_FETCH_FAILED",
            fields={"ticker": resolved_ticker, "exception": str(exc)},
        )
        log_event(
            logger,
            event="technical_data_fetch_completed",
            message="technical data fetch completed",
            level=logging.ERROR,
            fields={
                "ticker": resolved_ticker,
                "status": "error",
                "is_degraded": True,
                "error_code": "TECHNICAL_DATA_FETCH_FAILED",
                "rows": 0,
                "input_count": 0,
                "output_count": 0,
                "artifact_written": False,
            },
        )
        return TechnicalNodeResult(
            update=build_data_fetch_error_update(f"Data fetch failed: {str(exc)}"),
            goto="END",
        )

    daily_frame = bundle_result.frames.get("1d")
    if daily_frame is None or daily_frame.empty:
        log_event(
            logger,
            event="technical_data_fetch_empty",
            message="technical data fetch returned empty daily frame",
            level=logging.WARNING,
            error_code="TECHNICAL_DATA_EMPTY",
            fields={
                "ticker": resolved_ticker,
                "degrade_source": "market_data_provider",
                "fallback_mode": "terminate_empty_frame",
                "input_count": 0,
                "output_count": 0,
            },
        )
        log_event(
            logger,
            event="technical_data_fetch_completed",
            message="technical data fetch completed",
            level=logging.ERROR,
            fields={
                "ticker": resolved_ticker,
                "status": "error",
                "is_degraded": True,
                "error_code": "TECHNICAL_DATA_EMPTY",
                "rows": 0,
                "input_count": 0,
                "output_count": 0,
                "artifact_written": False,
            },
        )
        return TechnicalNodeResult(
            update=build_data_fetch_error_update("Empty daily data returned"),
            goto="END",
        )

    degraded_reasons: list[str] = list(bundle_result.degraded_reasons)
    ohlc_missing_reasons: list[str] = []
    for timeframe, frame in bundle_result.frames.items():
        missing_cols = []
        for col in ("open", "high", "low", "close"):
            if col not in frame.columns or frame[col].dropna().empty:
                missing_cols.append(col)
        if missing_cols:
            ohlc_missing_reasons.append(f"{timeframe}_OHLC_MISSING")
    if ohlc_missing_reasons:
        degraded_reasons.extend(ohlc_missing_reasons)

    if degraded_reasons:
        log_event(
            logger,
            event="technical_timeseries_bundle_degraded",
            message="technical timeseries bundle degraded",
            level=logging.WARNING,
            error_code="TECHNICAL_TIMESERIES_DEGRADED",
            fields={
                "ticker": resolved_ticker,
                "degraded_reasons": degraded_reasons,
            },
        )

    frames_payload = _frames_to_payload(bundle_result.frames)
    timeseries_bundle_payload = {
        "ticker": resolved_ticker,
        "as_of": datetime.now().isoformat(),
        "frames": frames_payload,
        "degraded_reasons": degraded_reasons or None,
    }
    timeseries_bundle_id = await runtime.save_timeseries_bundle(
        data=timeseries_bundle_payload,
        produced_by="technical_analysis.data_fetch",
        key_prefix=resolved_ticker,
    )

    price_data = _frame_to_price_payload(daily_frame)
    price_artifact_id = await runtime.save_price_series(
        data=price_data,
        produced_by="technical_analysis.data_fetch",
        key_prefix=resolved_ticker,
    )

    preview = build_data_fetch_preview(
        ticker=resolved_ticker,
        latest_price=daily_frame["price"].iloc[-1],
    )
    artifact = runtime.build_progress_artifact(
        f"Technical Analysis: Data fetched for {resolved_ticker}",
        preview,
    )
    input_count = len(bundle_result.frames)
    output_count = len(frames_payload)
    log_event(
        logger,
        event="technical_data_fetch_completed",
        message="technical data fetch completed",
        fields={
            "ticker": resolved_ticker,
            "status": "done",
            "is_degraded": False,
            "rows": len(daily_frame),
            "timeseries_bundle_id": timeseries_bundle_id,
            "input_count": input_count,
            "output_count": output_count,
            "artifact_written": True,
        },
    )

    return TechnicalNodeResult(
        update=build_data_fetch_success_update(
            price_artifact_id=price_artifact_id,
            timeseries_bundle_id=timeseries_bundle_id,
            artifact=artifact,
        ),
        goto="feature_compute",
    )


def _format_index(value: object) -> str:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)


def _series_to_payload(series: pd.Series) -> dict[str, float | None]:
    series = series.astype(object).where(pd.notnull(series), None)
    payload: dict[str, float | None] = {}
    for idx, raw in series.items():
        payload[_format_index(idx)] = None if raw is None else float(raw)
    return payload


def _frame_to_price_payload(frame: pd.DataFrame) -> dict[str, dict[str, float | None]]:
    price_series = _series_to_payload(frame["price"])
    volume_series = _series_to_payload(frame["volume"])
    return {
        "price_series": price_series,
        "volume_series": volume_series,
    }


def _frames_to_payload(
    frames: dict[str, pd.DataFrame],
) -> dict[str, dict[str, object]]:
    payload: dict[str, dict[str, object]] = {}
    for timeframe, frame in frames.items():
        if frame is None or frame.empty:
            continue
        index = frame.index
        start = _format_index(index[0])
        end = _format_index(index[-1])
        timezone = str(getattr(index, "tz", "")) if getattr(index, "tz", None) else None
        open_series = (
            _series_to_payload(frame["open"]) if "open" in frame.columns else {}
        )
        high_series = (
            _series_to_payload(frame["high"]) if "high" in frame.columns else {}
        )
        low_series = _series_to_payload(frame["low"]) if "low" in frame.columns else {}
        close_series = (
            _series_to_payload(frame["close"]) if "close" in frame.columns else {}
        )
        payload[timeframe] = {
            "timeframe": timeframe,
            "start": start,
            "end": end,
            "open_series": open_series,
            "high_series": high_series,
            "low_series": low_series,
            "close_series": close_series,
            "price_series": _series_to_payload(frame["price"]),
            "volume_series": _series_to_payload(frame["volume"]),
            "timezone": timezone,
            "metadata": {"rows": len(frame)},
        }
    return payload
