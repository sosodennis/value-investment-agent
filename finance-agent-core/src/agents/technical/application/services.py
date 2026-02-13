from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from src.agents.technical.domain.models import FracdiffSerializationResult
from src.agents.technical.domain.services import (
    build_full_report_payload,
    safe_float,
)
from src.common.tools.logger import get_logger
from src.common.types import AgentOutputArtifactPayload, JSONObject
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
class SemanticCommandUpdateResult:
    update: JSONObject


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


def _series_to_json(series: pd.Series) -> dict[str, float | None]:
    return {
        (
            key.strftime("%Y-%m-%d") if isinstance(key, pd.Timestamp) else str(key)
        ): safe_float(raw_value)
        for key, raw_value in series.to_dict().items()
    }


def serialize_fracdiff_outputs(
    *,
    fd_series: pd.Series,
    z_score_series: pd.Series,
    bollinger_data: JSONObject,
    stat_strength_data: JSONObject,
    obv_data: JSONObject,
) -> FracdiffSerializationResult:
    bollinger = {
        "upper": safe_float(bollinger_data.get("upper")),
        "middle": safe_float(bollinger_data.get("middle")),
        "lower": safe_float(bollinger_data.get("lower")),
        "state": str(bollinger_data.get("state") or "INSIDE"),
        "bandwidth": safe_float(bollinger_data.get("bandwidth")),
    }

    stat_strength = {
        "value": safe_float(stat_strength_data.get("value")),
    }

    obv = {
        "raw_obv_val": safe_float(obv_data.get("raw_obv_val")),
        "fd_obv_z": safe_float(obv_data.get("fd_obv_z")),
        "optimal_d": safe_float(obv_data.get("optimal_d")),
        "state": str(obv_data.get("state") or "NEUTRAL"),
    }

    return FracdiffSerializationResult(
        bollinger=bollinger,
        stat_strength=stat_strength,
        obv=obv,
        fracdiff_series=_series_to_json(fd_series),
        z_score_series=_series_to_json(z_score_series),
    )


def build_fracdiff_preview(
    *,
    ticker: str,
    latest_price: object,
    z_score: object,
    optimal_d: object,
    statistical_strength: object,
) -> JSONObject:
    latest_price_num = safe_float(latest_price) or 0.0
    z_score_num = safe_float(z_score) or 0.0
    optimal_d_num = safe_float(optimal_d) or 0.0
    strength_num = safe_float(statistical_strength) or 0.0

    return {
        "ticker": ticker,
        "latest_price_display": f"${latest_price_num:,.2f}",
        "signal_display": "🧬 COMPUTING...",
        "z_score_display": f"Z: {z_score_num:+.2f}",
        "optimal_d_display": f"d={optimal_d_num:.2f}",
        "strength_display": f"Strength: {strength_num:.1f}",
    }


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
    tags_dict: JSONObject,
    llm_interpretation: str,
    price_data: PriceSeriesArtifactData | None,
    chart_data: TechnicalChartArtifactData | None,
) -> SemanticFinalizeResult:
    direction = str(tags_dict.get("direction") or "NEUTRAL").upper()
    opt_d = float(technical_context.get("optimal_d", 0.5))

    raw_data: JSONObject = {}
    if price_data is not None and chart_data is not None:
        raw_data = {
            "price_series": price_data.price_series,
            "fracdiff_series": chart_data.fracdiff_series,
            "z_score_series": chart_data.z_score_series,
        }

    full_report_data_raw = build_full_report_payload(
        ticker=ticker,
        technical_context=technical_context,
        tags_dict=tags_dict,
        llm_interpretation=llm_interpretation,
        raw_data=raw_data,
    )

    ta_update = {
        "signal": tags_dict["direction"],
        "statistical_strength": tags_dict["statistical_state"],
        "risk_level": tags_dict["risk_level"],
        "llm_interpretation": llm_interpretation,
        "semantic_tags": tags_dict["tags"],
        "memory_strength": tags_dict["memory_strength"],
    }

    return SemanticFinalizeResult(
        direction=direction,
        opt_d=opt_d,
        raw_data=raw_data,
        full_report_data_raw=full_report_data_raw,
        ta_update=ta_update,
    )


def build_semantic_success_update(ta_update: JSONObject) -> SemanticCommandUpdateResult:
    return SemanticCommandUpdateResult(
        update={
            "technical_analysis": ta_update,
            "current_node": "semantic_translate",
            "internal_progress": {"semantic_translate": "done"},
            "node_statuses": {"technical_analysis": "done"},
        }
    )


def build_semantic_error_update(error_message: str) -> SemanticCommandUpdateResult:
    return SemanticCommandUpdateResult(
        update={
            "current_node": "semantic_translate",
            "internal_progress": {"semantic_translate": "error"},
            "node_statuses": {"technical_analysis": "error"},
            "error_logs": [
                {
                    "node": "semantic_translate",
                    "error": error_message,
                    "severity": "error",
                }
            ],
        }
    )


def build_data_fetch_error_update(error_message: str) -> JSONObject:
    return {
        "current_node": "data_fetch",
        "internal_progress": {"data_fetch": "error"},
        "node_statuses": {"technical_analysis": "error"},
        "error_logs": [
            {
                "node": "data_fetch",
                "error": error_message,
                "severity": "error",
            }
        ],
    }


def build_data_fetch_success_update(
    *,
    price_artifact_id: str,
    resolved_ticker: str,
    artifact: AgentOutputArtifactPayload,
) -> JSONObject:
    return {
        "technical_analysis": {
            "price_artifact_id": price_artifact_id,
            "ticker": resolved_ticker,
            "artifact": artifact,
        },
        "current_node": "data_fetch",
        "internal_progress": {
            "data_fetch": "done",
            "fracdiff_compute": "running",
        },
        "node_statuses": {"technical_analysis": "running"},
    }


def build_fracdiff_error_update(error_message: str) -> JSONObject:
    return {
        "current_node": "fracdiff_compute",
        "internal_progress": {"fracdiff_compute": "error"},
        "node_statuses": {"technical_analysis": "error"},
        "error_logs": [
            {
                "node": "fracdiff_compute",
                "error": error_message,
                "severity": "error",
            }
        ],
    }


def build_fracdiff_success_update(
    *,
    latest_price: float | None,
    optimal_d: float | None,
    z_score_latest: float | None,
    chart_data_id: str,
    window_length: int,
    adf_statistic: float | None,
    adf_pvalue: float | None,
    bollinger: JSONObject,
    statistical_strength_val: object,
    macd: JSONObject,
    obv: JSONObject,
    artifact: AgentOutputArtifactPayload,
) -> JSONObject:
    return {
        "technical_analysis": {
            "latest_price": latest_price,
            "optimal_d": optimal_d,
            "z_score_latest": z_score_latest,
            "chart_data_id": chart_data_id,
            "window_length": window_length,
            "adf_statistic": adf_statistic,
            "adf_pvalue": adf_pvalue,
            "bollinger": bollinger,
            "statistical_strength_val": statistical_strength_val,
            "macd": macd,
            "obv": obv,
            "artifact": artifact,
        },
        "current_node": "fracdiff_compute",
        "internal_progress": {
            "fracdiff_compute": "done",
            "semantic_translate": "running",
        },
    }
