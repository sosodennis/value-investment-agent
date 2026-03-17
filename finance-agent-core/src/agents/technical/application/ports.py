from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from src.agents.technical.application.fracdiff_runtime_contracts import (
    BollingerInput,
    FracdiffBacktestInputs,
    FracdiffRuntimeResult,
    ObvInput,
    StatisticalStrengthInput,
)
from src.agents.technical.interface.contracts import AnalystPerspectiveModel
from src.agents.technical.subdomains.verification import (
    BacktestResults,
    WalkForwardResult,
)
from src.interface.artifacts.artifact_data_models import (
    PriceSeriesArtifactData,
    TechnicalAlertsArtifactData,
    TechnicalChartArtifactData,
    TechnicalDirectionScorecardArtifactData,
    TechnicalFeaturePackArtifactData,
    TechnicalFusionReportArtifactData,
    TechnicalIndicatorSeriesArtifactData,
    TechnicalPatternPackArtifactData,
    TechnicalRegimePackArtifactData,
    TechnicalTimeseriesBundleArtifactData,
    TechnicalVerificationReportArtifactData,
)
from src.shared.kernel.types import JSONObject


@dataclass(frozen=True)
class TechnicalProviderFailure:
    failure_code: str
    reason: str | None = None
    http_status: int | None = None


@dataclass(frozen=True)
class TechnicalInterpretationInput:
    ticker: str
    direction: str
    risk_level: str
    confidence: float | None
    confidence_calibrated: float | None
    summary_tags: tuple[str, ...]
    evidence_items: tuple[str, ...]
    momentum_extremes: JSONObject | None
    setup_context: JSONObject | None
    validation_context: JSONObject | None
    diagnostics_context: JSONObject | None


@dataclass(frozen=True)
class TechnicalInterpretationResult:
    perspective: AnalystPerspectiveModel
    is_fallback: bool = False
    failure: TechnicalProviderFailure | None = None


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

    async def save_indicator_series(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    async def load_indicator_series(
        self, artifact_id: str | None
    ) -> TechnicalIndicatorSeriesArtifactData | None: ...

    async def save_alerts(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    async def load_alerts(
        self, artifact_id: str | None
    ) -> TechnicalAlertsArtifactData | None: ...

    async def save_timeseries_bundle(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    async def load_timeseries_bundle(
        self, artifact_id: str | None
    ) -> TechnicalTimeseriesBundleArtifactData | None: ...

    async def save_feature_pack(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    async def load_feature_pack(
        self, artifact_id: str | None
    ) -> TechnicalFeaturePackArtifactData | None: ...

    async def save_pattern_pack(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    async def load_pattern_pack(
        self, artifact_id: str | None
    ) -> TechnicalPatternPackArtifactData | None: ...

    async def save_regime_pack(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    async def load_regime_pack(
        self, artifact_id: str | None
    ) -> TechnicalRegimePackArtifactData | None: ...

    async def save_fusion_report(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    async def load_fusion_report(
        self, artifact_id: str | None
    ) -> TechnicalFusionReportArtifactData | None: ...

    async def save_direction_scorecard(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    async def load_direction_scorecard(
        self, artifact_id: str | None
    ) -> TechnicalDirectionScorecardArtifactData | None: ...

    async def save_verification_report(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...

    async def load_verification_report(
        self, artifact_id: str | None
    ) -> TechnicalVerificationReportArtifactData | None: ...

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


class ITechnicalInterpretationProvider(Protocol):
    def generate_interpretation(
        self,
        payload: TechnicalInterpretationInput,
    ) -> Awaitable[TechnicalInterpretationResult]: ...


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
