from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from src.agents.technical.application.fracdiff_runtime_contracts import (
    BollingerInput,
    ObvInput,
    StatisticalStrengthInput,
)
from src.agents.technical.application.semantic_context_formatter_service import (
    format_backtest_for_llm,
    format_wfa_for_llm,
)
from src.agents.technical.domain.backtest import (
    BacktestResults,
    CombinedBacktester,
    WalkForwardOptimizer,
    WalkForwardResult,
)


@dataclass(frozen=True)
class TechnicalBacktestRuntimeService:
    backtester_factory: Callable[..., CombinedBacktester] = CombinedBacktester
    wfa_optimizer_factory: Callable[[CombinedBacktester], WalkForwardOptimizer] = (
        WalkForwardOptimizer
    )
    format_backtest_for_llm_fn: Callable[[BacktestResults], str] = (
        format_backtest_for_llm
    )
    format_wfa_for_llm_fn: Callable[[WalkForwardResult | None], str] = (
        format_wfa_for_llm
    )

    def create_backtester(
        self,
        *,
        price_series: pd.Series,
        z_score_series: pd.Series,
        stat_strength_dict: StatisticalStrengthInput,
        obv_dict: ObvInput,
        bollinger_dict: BollingerInput,
        rf_series: pd.Series | None,
    ) -> CombinedBacktester:
        return self.backtester_factory(
            price_series=price_series,
            z_score_series=z_score_series,
            stat_strength_dict=stat_strength_dict,
            obv_dict=obv_dict,
            bollinger_dict=bollinger_dict,
            rf_series=rf_series,
        )

    def create_wfa_optimizer(
        self, backtester: CombinedBacktester
    ) -> WalkForwardOptimizer:
        return self.wfa_optimizer_factory(backtester)

    def run_backtest(
        self, backtester: CombinedBacktester, transaction_cost: float = 0.0005
    ) -> BacktestResults:
        return backtester.run(transaction_cost=transaction_cost)

    def run_wfa(
        self,
        wfa_optimizer: WalkForwardOptimizer,
        train_window: int = 252,
        test_window: int = 63,
    ) -> WalkForwardResult | None:
        return wfa_optimizer.run(train_window=train_window, test_window=test_window)

    def format_backtest_for_llm(self, backtest_result: BacktestResults) -> str:
        return self.format_backtest_for_llm_fn(backtest_result)

    def format_wfa_for_llm(self, wfa_result: WalkForwardResult | None) -> str:
        return self.format_wfa_for_llm_fn(wfa_result)
