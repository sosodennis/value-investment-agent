from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Protocol

import pandas as pd

from src.agents.technical.application.ports import ITechnicalFracdiffRuntime
from src.agents.technical.application.state_readers import (
    resolved_ticker_from_state,
    technical_state_from_state,
)
from src.agents.technical.application.state_updates import (
    build_fracdiff_error_update,
    build_fracdiff_success_update,
)
from src.agents.technical.interface.serializers import build_fracdiff_progress_preview
from src.interface.artifacts.artifact_data_models import PriceSeriesArtifactData
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject
from src.shared.kernel.workflow_contracts import WorkflowNodeResult

logger = get_logger(__name__)
TechnicalNodeResult = WorkflowNodeResult


class FracdiffComputeRuntime(Protocol):
    async def load_price_series(
        self, artifact_id: str
    ) -> PriceSeriesArtifactData | None: ...

    async def save_chart_data(
        self,
        *,
        data: JSONObject,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    build_progress_artifact: Callable[[str, JSONObject], dict[str, object]]


async def run_fracdiff_compute_use_case(
    runtime: FracdiffComputeRuntime,
    state: Mapping[str, object],
    *,
    fracdiff_runtime: ITechnicalFracdiffRuntime,
) -> TechnicalNodeResult:
    log_event(
        logger,
        event="technical_fracdiff_started",
        message="technical fracdiff computation started",
    )

    technical_context = technical_state_from_state(state)
    price_artifact_id = technical_context.price_artifact_id
    if price_artifact_id is None:
        log_event(
            logger,
            event="technical_fracdiff_missing_price_artifact_id",
            message="technical fracdiff failed due to missing price artifact id",
            level=logging.ERROR,
            error_code="TECHNICAL_PRICE_ARTIFACT_ID_MISSING",
        )
        return TechnicalNodeResult(
            update=build_fracdiff_error_update("Missing price artifact ID"),
            goto="END",
        )

    try:
        price_data = await runtime.load_price_series(price_artifact_id)
        if price_data is None:
            log_event(
                logger,
                event="technical_fracdiff_price_artifact_not_found",
                message="technical fracdiff failed due to missing price artifact",
                level=logging.ERROR,
                error_code="TECHNICAL_PRICE_ARTIFACT_NOT_FOUND",
                fields={"price_artifact_id": price_artifact_id},
            )
            return TechnicalNodeResult(
                update=build_fracdiff_error_update("Price artifact not found in store"),
                goto="END",
            )

        prices = pd.Series(price_data.price_series)
        prices.index = pd.to_datetime(prices.index)
        volumes = pd.Series(price_data.volume_series)
        volumes.index = pd.to_datetime(volumes.index)

        result = fracdiff_runtime.compute(prices=prices, volumes=volumes)

        key_prefix = state.get("ticker")
        chart_data_id = await runtime.save_chart_data(
            data=result.chart_data,
            produced_by="technical_analysis.fracdiff_compute",
            key_prefix=key_prefix if isinstance(key_prefix, str) else None,
        )
    except Exception as exc:
        log_event(
            logger,
            event="technical_fracdiff_failed",
            message="technical fracdiff computation failed",
            level=logging.ERROR,
            error_code="TECHNICAL_FRACDIFF_FAILED",
            fields={"exception": str(exc)},
        )
        return TechnicalNodeResult(
            update=build_fracdiff_error_update(f"Computation crashed: {str(exc)}"),
            goto="END",
        )

    ticker_value = resolved_ticker_from_state(state) or "N/A"
    preview = build_fracdiff_progress_preview(
        ticker=ticker_value,
        latest_price=result.latest_price,
        z_score=result.z_score_latest,
        optimal_d=result.optimal_d,
        statistical_strength=result.statistical_strength_val,
    )
    artifact = runtime.build_progress_artifact(
        f"Technical Analysis: Patterns computed for {ticker_value}",
        preview,
    )

    return TechnicalNodeResult(
        update=build_fracdiff_success_update(
            latest_price=result.latest_price,
            optimal_d=result.optimal_d,
            z_score_latest=result.z_score_latest,
            chart_data_id=chart_data_id,
            window_length=result.window_length,
            adf_statistic=result.adf_statistic,
            adf_pvalue=result.adf_pvalue,
            bollinger=result.bollinger,
            statistical_strength_val=result.statistical_strength_val,
            macd=result.macd,
            obv=result.obv,
            artifact=artifact,
        ),
        goto="semantic_translate",
    )
