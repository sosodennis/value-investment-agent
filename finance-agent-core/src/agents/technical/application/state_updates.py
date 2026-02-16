from __future__ import annotations

from dataclasses import dataclass

from src.shared.kernel.types import AgentOutputArtifactPayload, JSONObject


@dataclass(frozen=True)
class SemanticCommandUpdateResult:
    update: JSONObject


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
