from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from src.agents.technical.domain.models import (
    SemanticConfluenceInput,
    SemanticTagPolicyInput,
    SemanticTagPolicyResult,
)
from src.common.tools.logger import get_logger
from src.common.types import JSONObject
from src.interface.artifact_api_models import (
    PriceSeriesArtifactData,
    TechnicalChartArtifactData,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class BacktestContextResult:
    backtest_context: str
    wfa_context: str
    price_data: PriceSeriesArtifactData | None
    chart_data: TechnicalChartArtifactData | None


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


class _TechnicalPortLike(Protocol):
    async def load_price_and_chart_data(
        self,
        price_artifact_id: object,
        chart_artifact_id: object,
    ) -> tuple[PriceSeriesArtifactData | None, TechnicalChartArtifactData | None]: ...


class _BacktesterLike(Protocol):
    def run(self, transaction_cost: float) -> object: ...


class _WFAOptimizerLike(Protocol):
    def run(self, train_window: int, test_window: int) -> object: ...


async def assemble_backtest_context(
    *,
    technical_port: _TechnicalPortLike,
    price_artifact_id: object,
    chart_artifact_id: object,
    calculate_statistical_strength_fn: Callable[[pd.Series], JSONObject],
    calculate_fd_bollinger_fn: Callable[[pd.Series], JSONObject],
    calculate_fd_obv_fn: Callable[[pd.Series, pd.Series], JSONObject],
    fetch_risk_free_series_fn: Callable[..., pd.Series],
    backtester_factory: Callable[..., _BacktesterLike],
    format_backtest_for_llm_fn: Callable[[object], str],
    wfa_optimizer_factory: Callable[[_BacktesterLike], _WFAOptimizerLike],
    format_wfa_for_llm_fn: Callable[[object], str],
) -> BacktestContextResult:
    price_data: PriceSeriesArtifactData | None = None
    chart_data: TechnicalChartArtifactData | None = None
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

        stat_strength_full = calculate_statistical_strength_fn(z_score_series)
        bb_full = calculate_fd_bollinger_fn(fd_series)
        obv_full = calculate_fd_obv_fn(prices, volumes)
        rf_series = fetch_risk_free_series_fn(period="5y")

        backtester = backtester_factory(
            price_series=prices,
            z_score_series=z_score_series,
            stat_strength_dict=stat_strength_full,
            obv_dict=obv_full,
            bollinger_dict=bb_full,
            rf_series=rf_series,
        )

        bt_results = backtester.run(transaction_cost=0.0005)
        backtest_context = format_backtest_for_llm_fn(bt_results)

        try:
            wfa_optimizer = wfa_optimizer_factory(backtester)
            wfa_results = wfa_optimizer.run(train_window=252, test_window=63)
            wfa_context = format_wfa_for_llm_fn(wfa_results)
        except Exception:
            wfa_context = ""

        return BacktestContextResult(
            backtest_context=backtest_context,
            wfa_context=wfa_context,
            price_data=price_data,
            chart_data=chart_data,
        )
    except Exception as exc:
        logger.warning(
            "Backtesting failed: %s. Proceeding without statistical verification.",
            exc,
        )
        return BacktestContextResult(
            backtest_context="",
            wfa_context="",
            price_data=price_data,
            chart_data=chart_data,
        )


def assemble_semantic_finalize(
    *,
    ticker: str,
    technical_context: JSONObject,
    tags_result: SemanticTagPolicyResult,
    llm_interpretation: str,
    price_data: PriceSeriesArtifactData | None,
    chart_data: TechnicalChartArtifactData | None,
    build_full_report_payload_fn: Callable[..., JSONObject],
) -> SemanticFinalizeResult:
    direction = tags_result.direction.upper()
    opt_d = float(technical_context.get("optimal_d", 0.5))

    raw_data: JSONObject = {}
    if price_data is not None and chart_data is not None:
        raw_data = {
            "price_series": price_data.price_series,
            "fracdiff_series": chart_data.fracdiff_series,
            "z_score_series": chart_data.z_score_series,
        }

    full_report_data_raw = build_full_report_payload_fn(
        ticker=ticker,
        technical_context=technical_context,
        tags_dict=semantic_tags_to_dict(tags_result),
        llm_interpretation=llm_interpretation,
        raw_data=raw_data,
    )

    ta_update = {
        "signal": tags_result.direction,
        "statistical_strength": tags_result.statistical_state,
        "risk_level": tags_result.risk_level,
        "llm_interpretation": llm_interpretation,
        "semantic_tags": tags_result.tags,
        "memory_strength": tags_result.memory_strength,
    }

    return SemanticFinalizeResult(
        direction=direction,
        opt_d=opt_d,
        raw_data=raw_data,
        full_report_data_raw=full_report_data_raw,
        ta_update=ta_update,
    )


async def execute_semantic_pipeline(
    *,
    ticker: str,
    technical_context: JSONObject,
    assemble_fn: Callable[[SemanticTagPolicyInput], SemanticTagPolicyResult],
    generate_interpretation_fn: Callable[..., Awaitable[str]],
    calculate_statistical_strength_fn: Callable[[pd.Series], JSONObject],
    calculate_fd_bollinger_fn: Callable[[pd.Series], JSONObject],
    calculate_fd_obv_fn: Callable[[pd.Series, pd.Series], JSONObject],
    fetch_risk_free_series_fn: Callable[..., pd.Series],
    backtester_factory: Callable[..., _BacktesterLike],
    format_backtest_for_llm_fn: Callable[[object], str],
    wfa_optimizer_factory: Callable[[_BacktesterLike], _WFAOptimizerLike],
    format_wfa_for_llm_fn: Callable[[object], str],
    technical_port: _TechnicalPortLike,
    price_artifact_id: object,
    chart_artifact_id: object,
    build_full_report_payload_fn: Callable[..., JSONObject],
) -> SemanticPipelineResult:
    tags_result = assemble_fn(build_semantic_policy_input(technical_context))

    backtest_context_result = await assemble_backtest_context(
        technical_port=technical_port,
        price_artifact_id=price_artifact_id,
        chart_artifact_id=chart_artifact_id,
        calculate_statistical_strength_fn=calculate_statistical_strength_fn,
        calculate_fd_bollinger_fn=calculate_fd_bollinger_fn,
        calculate_fd_obv_fn=calculate_fd_obv_fn,
        fetch_risk_free_series_fn=fetch_risk_free_series_fn,
        backtester_factory=backtester_factory,
        format_backtest_for_llm_fn=format_backtest_for_llm_fn,
        wfa_optimizer_factory=wfa_optimizer_factory,
        format_wfa_for_llm_fn=format_wfa_for_llm_fn,
    )

    llm_interpretation = await generate_interpretation_fn(
        semantic_tags_to_dict(tags_result),
        ticker,
        backtest_context_result.backtest_context,
        backtest_context_result.wfa_context,
    )

    semantic_finalize_result = assemble_semantic_finalize(
        ticker=ticker,
        technical_context=technical_context,
        tags_result=tags_result,
        llm_interpretation=llm_interpretation,
        price_data=backtest_context_result.price_data,
        chart_data=backtest_context_result.chart_data,
        build_full_report_payload_fn=build_full_report_payload_fn,
    )

    return SemanticPipelineResult(
        tags_result=tags_result,
        llm_interpretation=llm_interpretation,
        backtest_context_result=backtest_context_result,
        semantic_finalize_result=semantic_finalize_result,
    )


def build_semantic_policy_input(
    technical_context: JSONObject,
) -> SemanticTagPolicyInput:
    z_score_raw = technical_context.get("z_score_latest")
    optimal_d_raw = technical_context.get("optimal_d")
    z_score = float(z_score_raw) if isinstance(z_score_raw, int | float) else 0.0
    optimal_d = float(optimal_d_raw) if isinstance(optimal_d_raw, int | float) else 0.5

    bollinger_raw = technical_context.get("bollinger")
    bollinger_state = "INSIDE"
    if isinstance(bollinger_raw, dict):
        bollinger_state_raw = bollinger_raw.get("state")
        if isinstance(bollinger_state_raw, str) and bollinger_state_raw:
            bollinger_state = bollinger_state_raw

    macd_raw = technical_context.get("macd")
    macd_momentum = "NEUTRAL"
    if isinstance(macd_raw, dict):
        macd_momentum_raw = macd_raw.get("momentum_state")
        if isinstance(macd_momentum_raw, str) and macd_momentum_raw:
            macd_momentum = macd_momentum_raw

    obv_raw = technical_context.get("obv")
    obv_state = "NEUTRAL"
    obv_z = 0.0
    if isinstance(obv_raw, dict):
        obv_state_raw = obv_raw.get("state")
        if isinstance(obv_state_raw, str) and obv_state_raw:
            obv_state = obv_state_raw
        obv_z_raw = obv_raw.get("fd_obv_z")
        if isinstance(obv_z_raw, int | float):
            obv_z = float(obv_z_raw)

    statistical_strength_raw = technical_context.get("statistical_strength_val")
    statistical_strength = (
        float(statistical_strength_raw)
        if isinstance(statistical_strength_raw, int | float)
        else 50.0
    )

    return SemanticTagPolicyInput(
        z_score=z_score,
        optimal_d=optimal_d,
        confluence=SemanticConfluenceInput(
            bollinger_state=bollinger_state,
            statistical_strength=statistical_strength,
            macd_momentum=macd_momentum,
            obv_state=obv_state,
            obv_z=obv_z,
        ),
    )


def semantic_tags_to_dict(tags_result: SemanticTagPolicyResult) -> JSONObject:
    return {
        "tags": tags_result.tags,
        "direction": tags_result.direction,
        "risk_level": tags_result.risk_level,
        "memory_strength": tags_result.memory_strength,
        "statistical_state": tags_result.statistical_state,
        "z_score": tags_result.z_score,
        "confluence": {
            "bollinger_state": tags_result.confluence.bollinger_state,
            "statistical_strength": tags_result.confluence.statistical_strength,
            "macd_momentum": tags_result.confluence.macd_momentum,
            "obv_state": tags_result.confluence.obv_state,
        },
        "evidence_list": tags_result.evidence_list,
    }
