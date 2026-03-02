from __future__ import annotations

import logging

import pandas as pd

from src.agents.technical.application.ports import (
    ITechnicalBacktestRuntime,
    ITechnicalFracdiffRuntime,
    ITechnicalMarketDataProvider,
)
from src.agents.technical.application.semantic_pipeline_contracts import (
    BacktestContextResult,
    TechnicalPortLike,
)
from src.shared.kernel.tools.logger import get_logger, log_event

logger = get_logger(__name__)


async def assemble_backtest_context(
    *,
    technical_port: TechnicalPortLike,
    price_artifact_id: str | None,
    chart_artifact_id: str | None,
    fracdiff_runtime: ITechnicalFracdiffRuntime,
    market_data_provider: ITechnicalMarketDataProvider,
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
        rf_series = market_data_provider.fetch_risk_free_series(period="5y")

        backtester = backtest_runtime.create_backtester(
            price_series=prices,
            z_score_series=z_score_series,
            stat_strength_dict=backtest_inputs.stat_strength_dict,
            obv_dict=backtest_inputs.obv_dict,
            bollinger_dict=backtest_inputs.bollinger_dict,
            rf_series=rf_series,
        )

        bt_results = backtest_runtime.run_backtest(backtester, transaction_cost=0.0005)
        backtest_context = backtest_runtime.format_backtest_for_llm(bt_results)

        try:
            wfa_optimizer = backtest_runtime.create_wfa_optimizer(backtester)
            wfa_results = backtest_runtime.run_wfa(
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
        )
    except Exception as exc:
        log_event(
            logger,
            event="technical_semantic_backtest_context_failed",
            message="technical semantic backtest context failed; proceeding without statistical verification",
            level=logging.WARNING,
            error_code="TECHNICAL_SEMANTIC_BACKTEST_CONTEXT_FAILED",
            fields={"exception": str(exc)},
        )
        return BacktestContextResult(
            backtest_context="",
            wfa_context="",
            price_data=price_data,
            chart_data=chart_data,
        )
