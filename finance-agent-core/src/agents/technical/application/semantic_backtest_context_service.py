from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TypeVar

import pandas as pd

from src.agents.technical.application.ports import (
    ITechnicalBacktestRuntime,
    ITechnicalFracdiffRuntime,
)
from src.agents.technical.application.semantic_pipeline_contracts import (
    BacktestContextResult,
    TechnicalPortLike,
)
from src.agents.technical.subdomains.market_data.application.ports import (
    IMarketDataProvider,
)
from src.shared.kernel.tools.logger import get_logger, log_event

logger = get_logger(__name__)
_COMPUTE_CONCURRENCY_LIMIT = 2
_T = TypeVar("_T")
_compute_semaphore: asyncio.Semaphore | None = None


def _get_compute_semaphore() -> asyncio.Semaphore:
    global _compute_semaphore
    if _compute_semaphore is None:
        _compute_semaphore = asyncio.Semaphore(_COMPUTE_CONCURRENCY_LIMIT)
    return _compute_semaphore


async def _offload_compute(
    func: Callable[..., _T],
    /,
    *args: object,
    **kwargs: object,
) -> _T:
    # Bound heavy compute concurrency so semantic nodes do not flood thread workers.
    async with _get_compute_semaphore():
        return await asyncio.to_thread(func, *args, **kwargs)


async def assemble_backtest_context(
    *,
    technical_port: TechnicalPortLike,
    price_artifact_id: str | None,
    chart_artifact_id: str | None,
    fracdiff_runtime: ITechnicalFracdiffRuntime,
    market_data_provider: IMarketDataProvider,
    backtest_runtime: ITechnicalBacktestRuntime,
) -> BacktestContextResult:
    price_data = None
    chart_data = None
    try:
        price_data, chart_data = await technical_port.load_price_and_chart_data(
            price_artifact_id, chart_artifact_id
        )
        if price_data is None or chart_data is None:
            raise ValueError("Artifacts not found")

        prices = pd.Series(price_data.price_series)
        prices.index = pd.to_datetime(prices.index)

        volumes = pd.Series(price_data.volume_series)
        volumes.index = pd.to_datetime(volumes.index)

        fd_series = pd.Series(chart_data.fracdiff_series)
        fd_series.index = pd.to_datetime(fd_series.index)

        z_score_series = pd.Series(chart_data.z_score_series)
        z_score_series.index = pd.to_datetime(z_score_series.index)

        backtest_inputs = fracdiff_runtime.build_backtest_inputs(
            prices=prices,
            volumes=volumes,
            fd_series=fd_series,
            z_score_series=z_score_series,
        )
        risk_free_result = await asyncio.to_thread(
            market_data_provider.fetch_risk_free_series,
            "5y",
        )
        rf_series = risk_free_result.data
        if risk_free_result.failure is not None:
            log_event(
                logger,
                event="technical_semantic_risk_free_unavailable",
                message="technical semantic backtest context missing risk-free series; continuing with default fallback",
                level=logging.WARNING,
                error_code=risk_free_result.failure.failure_code,
                fields={
                    "degrade_source": "market_data_provider.risk_free",
                    "provider_failure_code": risk_free_result.failure.failure_code,
                    "provider_reason": risk_free_result.failure.reason,
                    "fallback_mode": "backtester_default_risk_free",
                    "input_count": 1,
                    "output_count": 0,
                },
            )

        backtester = backtest_runtime.create_backtester(
            price_series=prices,
            z_score_series=z_score_series,
            stat_strength_dict=backtest_inputs.stat_strength_dict,
            obv_dict=backtest_inputs.obv_dict,
            bollinger_dict=backtest_inputs.bollinger_dict,
            rf_series=rf_series,
        )

        bt_results = await _offload_compute(
            backtest_runtime.run_backtest,
            backtester,
            transaction_cost=0.0005,
        )
        backtest_context = backtest_runtime.format_backtest_for_llm(bt_results)

        try:
            wfa_optimizer = backtest_runtime.create_wfa_optimizer(backtester)
            wfa_results = await _offload_compute(
                backtest_runtime.run_wfa,
                wfa_optimizer,
                train_window=252,
                test_window=63,
            )
            wfa_context = backtest_runtime.format_wfa_for_llm(wfa_results)
        except Exception:
            wfa_context = ""

        return BacktestContextResult(
            backtest_context=backtest_context,
            wfa_context=wfa_context,
            price_data=price_data,
            chart_data=chart_data,
            is_degraded=False,
            failure_code=None,
        )
    except Exception as exc:
        failure_code = "TECHNICAL_SEMANTIC_BACKTEST_CONTEXT_FAILED"
        log_event(
            logger,
            event="technical_semantic_backtest_context_failed",
            message="technical semantic backtest context failed; proceeding without statistical verification",
            level=logging.WARNING,
            error_code=failure_code,
            fields={
                "exception": str(exc),
                "degrade_source": "semantic_backtest_context",
                "fallback_mode": "continue_without_backtest_context",
                "price_artifact_id": price_artifact_id,
                "chart_artifact_id": chart_artifact_id,
                "input_count": int(price_artifact_id is not None)
                + int(chart_artifact_id is not None),
                "output_count": 0,
            },
        )
        return BacktestContextResult(
            backtest_context="",
            wfa_context="",
            price_data=price_data,
            chart_data=chart_data,
            is_degraded=True,
            failure_code=failure_code,
        )
