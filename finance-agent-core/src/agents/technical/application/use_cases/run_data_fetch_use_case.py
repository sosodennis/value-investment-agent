from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from typing import Protocol

import pandas as pd

from src.agents.technical.application.ports import ITechnicalMarketDataProvider
from src.agents.technical.application.state_readers import resolved_ticker_from_state
from src.agents.technical.application.state_updates import (
    build_data_fetch_error_update,
    build_data_fetch_success_update,
)
from src.agents.technical.interface.serializers import build_data_fetch_preview
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

    build_progress_artifact: Callable[[str, JSONObject], dict[str, object]]


async def run_data_fetch_use_case(
    runtime: DataFetchRuntime,
    state: Mapping[str, object],
    *,
    market_data_provider: ITechnicalMarketDataProvider,
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
                "artifact_written": False,
            },
        )
        return TechnicalNodeResult(
            update=build_data_fetch_error_update("No resolved ticker available"),
            goto="END",
        )

    try:
        fetch_result = await asyncio.to_thread(
            market_data_provider.fetch_daily_ohlcv,
            resolved_ticker,
            "5y",
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
                "artifact_written": False,
            },
        )
        return TechnicalNodeResult(
            update=build_data_fetch_error_update(f"Data fetch failed: {str(exc)}"),
            goto="END",
        )

    provider_failure = fetch_result.failure
    if provider_failure is not None:
        if provider_failure.failure_code == "TECHNICAL_OHLCV_EMPTY":
            log_event(
                logger,
                event="technical_data_fetch_empty",
                message="technical data fetch returned empty frame",
                level=logging.WARNING,
                error_code="TECHNICAL_DATA_EMPTY",
                fields={
                    "ticker": resolved_ticker,
                    "degrade_source": "market_data_provider",
                    "provider_failure_code": provider_failure.failure_code,
                    "provider_reason": provider_failure.reason,
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
                    "artifact_written": False,
                },
            )
            return TechnicalNodeResult(
                update=build_data_fetch_error_update(
                    "Empty data returned from provider"
                ),
                goto="END",
            )

        log_event(
            logger,
            event="technical_data_fetch_failed",
            message="technical data fetch failed",
            level=logging.ERROR,
            error_code="TECHNICAL_DATA_FETCH_FAILED",
            fields={
                "ticker": resolved_ticker,
                "degrade_source": "market_data_provider",
                "provider_failure_code": provider_failure.failure_code,
                "provider_reason": provider_failure.reason,
                "fallback_mode": "terminate_provider_failure",
                "input_count": 1,
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
                "error_code": "TECHNICAL_DATA_FETCH_FAILED",
                "rows": 0,
                "artifact_written": False,
            },
        )
        return TechnicalNodeResult(
            update=build_data_fetch_error_update(
                f"Data fetch failed: {provider_failure.failure_code}"
            ),
            goto="END",
        )

    df = fetch_result.data
    if df is None or df.empty:
        log_event(
            logger,
            event="technical_data_fetch_empty",
            message="technical data fetch returned empty frame",
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
                "artifact_written": False,
            },
        )
        return TechnicalNodeResult(
            update=build_data_fetch_error_update("Empty data returned from provider"),
            goto="END",
        )

    price_series = df["price"].rename(index=lambda x: x.strftime("%Y-%m-%d"))
    volume_series = df["volume"].rename(index=lambda x: x.strftime("%Y-%m-%d"))
    price_data = {
        "price_series": price_series.astype(object)
        .where(pd.notnull(price_series), None)
        .to_dict(),
        "volume_series": volume_series.astype(object)
        .where(pd.notnull(volume_series), None)
        .to_dict(),
    }

    price_artifact_id = await runtime.save_price_series(
        data=price_data,
        produced_by="technical_analysis.data_fetch",
        key_prefix=resolved_ticker,
    )

    preview = build_data_fetch_preview(
        ticker=resolved_ticker,
        latest_price=df["price"].iloc[-1],
    )
    artifact = runtime.build_progress_artifact(
        f"Technical Analysis: Data fetched for {resolved_ticker}",
        preview,
    )
    log_event(
        logger,
        event="technical_data_fetch_completed",
        message="technical data fetch completed",
        fields={
            "ticker": resolved_ticker,
            "status": "done",
            "is_degraded": False,
            "rows": len(df),
            "artifact_written": True,
        },
    )

    return TechnicalNodeResult(
        update=build_data_fetch_success_update(
            price_artifact_id=price_artifact_id,
            artifact=artifact,
        ),
        goto="fracdiff_compute",
    )
