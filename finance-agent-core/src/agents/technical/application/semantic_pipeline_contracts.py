from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.agents.technical.domain.signal_policy import SemanticTagPolicyResult
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


class TechnicalPortLike(Protocol):
    async def load_price_and_chart_data(
        self,
        price_artifact_id: str | None,
        chart_artifact_id: str | None,
    ) -> tuple[PriceSeriesDataLike | None, TechnicalChartDataLike | None]: ...
