from __future__ import annotations

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
    if resolved_ticker is None:
        log_event(
            logger,
            event="technical_data_fetch_missing_ticker",
            message="technical data fetch skipped due to missing resolved ticker",
            level=logging.ERROR,
            error_code="TECHNICAL_TICKER_MISSING",
        )
        return TechnicalNodeResult(
            update=build_data_fetch_error_update("No resolved ticker available"),
            goto="END",
        )

    log_event(
        logger,
        event="technical_data_fetch_started",
        message="technical data fetch started",
        fields={"ticker": resolved_ticker},
    )

    try:
        df = market_data_provider.fetch_daily_ohlcv(resolved_ticker, period="5y")
    except Exception as exc:
        log_event(
            logger,
            event="technical_data_fetch_failed",
            message="technical data fetch failed",
            level=logging.ERROR,
            error_code="TECHNICAL_DATA_FETCH_FAILED",
            fields={"ticker": resolved_ticker, "exception": str(exc)},
        )
        return TechnicalNodeResult(
            update=build_data_fetch_error_update(f"Data fetch failed: {str(exc)}"),
            goto="END",
        )

    if df is None or df.empty:
        log_event(
            logger,
            event="technical_data_fetch_empty",
            message="technical data fetch returned empty frame",
            level=logging.WARNING,
            error_code="TECHNICAL_DATA_EMPTY",
            fields={"ticker": resolved_ticker},
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

    return TechnicalNodeResult(
        update=build_data_fetch_success_update(
            price_artifact_id=price_artifact_id,
            resolved_ticker=resolved_ticker,
            artifact=artifact,
        ),
        goto="fracdiff_compute",
    )
