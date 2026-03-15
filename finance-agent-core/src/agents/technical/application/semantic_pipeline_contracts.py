from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.agents.technical.subdomains.signal_fusion import SemanticTagPolicyResult
from src.interface.artifacts.artifact_data_models import (
    TechnicalVerificationReportArtifactData,
)
from src.shared.kernel.types import JSONObject


class PriceSeriesDataLike(Protocol):
    price_series: dict[str, float]
    volume_series: dict[str, float]


class TechnicalChartDataLike(Protocol):
    fracdiff_series: dict[str, float]
    z_score_series: dict[str, float]


@dataclass(frozen=True)
class BacktestContextResult:
    backtest_context: str
    wfa_context: str
    price_data: PriceSeriesDataLike | None
    chart_data: TechnicalChartDataLike | None
    is_degraded: bool = False
    failure_code: str | None = None


@dataclass(frozen=True)
class SemanticFinalizeResult:
    direction: str
    opt_d: float
    raw_data: JSONObject
    full_report_data_raw: JSONObject
    ta_update: JSONObject


@dataclass(frozen=True)
class SemanticPipelineResult:
    tags_result: SemanticTagPolicyResult
    llm_interpretation: str
    backtest_context_result: BacktestContextResult
    semantic_finalize_result: SemanticFinalizeResult
    llm_is_fallback: bool = False
    llm_failure_code: str | None = None
    is_degraded: bool = False
    degraded_reasons: tuple[str, ...] = ()


class TechnicalPortLike(Protocol):
    async def load_price_and_chart_data(
        self,
        price_artifact_id: str | None,
        chart_artifact_id: str | None,
    ) -> tuple[PriceSeriesDataLike | None, TechnicalChartDataLike | None]: ...

    async def load_verification_report(
        self,
        artifact_id: str | None,
    ) -> TechnicalVerificationReportArtifactData | None: ...
