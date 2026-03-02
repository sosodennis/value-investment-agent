from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol

import pandas as pd

from src.agents.technical.application.fracdiff_runtime_contracts import (
    BollingerInput,
    FracdiffBacktestInputs,
    FracdiffRuntimeResult,
    ObvInput,
    StatisticalStrengthInput,
)
from src.agents.technical.domain.backtest import (
    BacktestResults,
    WalkForwardResult,
)
from src.interface.artifacts.artifact_data_models import (
    PriceSeriesArtifactData,
    TechnicalChartArtifactData,
)
from src.shared.kernel.types import JSONObject


class ITechnicalArtifactRepository(Protocol):
    async def save_price_series(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    async def load_price_series(
        self, artifact_id: str | None
    ) -> PriceSeriesArtifactData | None: ...

    async def save_chart_data(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    async def load_chart_data(
        self, artifact_id: str | None
    ) -> TechnicalChartArtifactData | None: ...

    async def save_full_report_canonical(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    async def load_price_and_chart_data(
        self,
        price_artifact_id: str | None,
        chart_artifact_id: str | None,
    ) -> tuple[PriceSeriesArtifactData | None, TechnicalChartArtifactData | None]: ...


class ITechnicalMarketDataProvider(Protocol):
    def fetch_daily_ohlcv(
        self, ticker_symbol: str, period: str = "5y"
    ) -> pd.DataFrame | None: ...

    def fetch_risk_free_series(self, period: str = "5y") -> pd.Series | None: ...


class ITechnicalInterpretationProvider(Protocol):
    def generate_interpretation(
        self,
        tags_dict: JSONObject,
        ticker: str,
        backtest_context: str = "",
        wfa_context: str = "",
    ) -> Awaitable[str]: ...


class ITechnicalBacktester(Protocol):
    def run(self, transaction_cost: float = 0.0005) -> BacktestResults: ...


class ITechnicalWfaOptimizer(Protocol):
    def run(
        self,
        train_window: int = 252,
        test_window: int = 63,
    ) -> WalkForwardResult | None: ...


class ITechnicalBacktestRuntime(Protocol):
    def create_backtester(
        self,
        *,
        price_series: pd.Series,
        z_score_series: pd.Series,
        stat_strength_dict: StatisticalStrengthInput,
        obv_dict: ObvInput,
        bollinger_dict: BollingerInput,
        rf_series: pd.Series | None,
    ) -> ITechnicalBacktester: ...

    def create_wfa_optimizer(
        self, backtester: ITechnicalBacktester
    ) -> ITechnicalWfaOptimizer: ...

    def run_backtest(
        self,
        backtester: ITechnicalBacktester,
        transaction_cost: float = 0.0005,
    ) -> BacktestResults: ...

    def run_wfa(
        self,
        wfa_optimizer: ITechnicalWfaOptimizer,
        train_window: int = 252,
        test_window: int = 63,
    ) -> WalkForwardResult | None: ...

    def format_backtest_for_llm(self, backtest_result: BacktestResults) -> str: ...

    def format_wfa_for_llm(self, wfa_result: WalkForwardResult | None) -> str: ...


class ITechnicalFracdiffRuntime(Protocol):
    def compute(
        self,
        *,
        prices: pd.Series,
        volumes: pd.Series,
    ) -> FracdiffRuntimeResult: ...

    def build_backtest_inputs(
        self,
        *,
        prices: pd.Series,
        volumes: pd.Series,
        fd_series: pd.Series,
        z_score_series: pd.Series,
    ) -> FracdiffBacktestInputs: ...
