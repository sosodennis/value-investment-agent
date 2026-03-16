from __future__ import annotations

import logging
from dataclasses import dataclass

from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import AgentOutputArtifactPayload, JSONObject
from src.workflow.state import find_state_hygiene_violations

logger = get_logger(__name__)


@dataclass(frozen=True)
class SemanticCommandUpdateResult:
    update: JSONObject


def build_data_fetch_error_update(error_message: str) -> JSONObject:
    return _guard_state_update(
        "data_fetch",
        {
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
        },
    )


def build_data_fetch_success_update(
    *,
    price_artifact_id: str,
    timeseries_bundle_id: str,
    artifact: AgentOutputArtifactPayload,
) -> JSONObject:
    return _guard_state_update(
        "data_fetch",
        {
            "technical_analysis": {
                "price_artifact_id": price_artifact_id,
                "timeseries_bundle_id": timeseries_bundle_id,
                "artifact": artifact,
            },
            "current_node": "data_fetch",
            "internal_progress": {
                "data_fetch": "done",
                "feature_compute": "running",
            },
            "node_statuses": {"technical_analysis": "running"},
        },
    )


def build_feature_compute_error_update(error_message: str) -> JSONObject:
    return _guard_state_update(
        "feature_compute",
        {
            "current_node": "feature_compute",
            "internal_progress": {"feature_compute": "error"},
            "node_statuses": {"technical_analysis": "error"},
            "error_logs": [
                {
                    "node": "feature_compute",
                    "error": error_message,
                    "severity": "error",
                }
            ],
        },
    )


def build_feature_compute_success_update(
    *,
    feature_pack_id: str,
    indicator_series_id: str | None = None,
    artifact: AgentOutputArtifactPayload,
) -> JSONObject:
    return _guard_state_update(
        "feature_compute",
        {
            "technical_analysis": {
                "feature_pack_id": feature_pack_id,
                "indicator_series_id": indicator_series_id,
                "artifact": artifact,
            },
            "current_node": "feature_compute",
            "internal_progress": {
                "feature_compute": "done",
                "pattern_compute": "running",
            },
            "node_statuses": {"technical_analysis": "running"},
        },
    )


def build_pattern_compute_error_update(error_message: str) -> JSONObject:
    return _guard_state_update(
        "pattern_compute",
        {
            "current_node": "pattern_compute",
            "internal_progress": {"pattern_compute": "error"},
            "node_statuses": {"technical_analysis": "error"},
            "error_logs": [
                {
                    "node": "pattern_compute",
                    "error": error_message,
                    "severity": "error",
                }
            ],
        },
    )


def build_pattern_compute_success_update(
    *,
    pattern_pack_id: str,
    artifact: AgentOutputArtifactPayload,
) -> JSONObject:
    return _guard_state_update(
        "pattern_compute",
        {
            "technical_analysis": {
                "pattern_pack_id": pattern_pack_id,
                "artifact": artifact,
            },
            "current_node": "pattern_compute",
            "internal_progress": {
                "pattern_compute": "done",
                "alerts_compute": "running",
            },
            "node_statuses": {"technical_analysis": "running"},
        },
    )


def build_alerts_compute_error_update(error_message: str) -> JSONObject:
    return _guard_state_update(
        "alerts_compute",
        {
            "current_node": "alerts_compute",
            "internal_progress": {"alerts_compute": "error"},
            "node_statuses": {"technical_analysis": "error"},
            "error_logs": [
                {
                    "node": "alerts_compute",
                    "error": error_message,
                    "severity": "error",
                }
            ],
        },
    )


def build_alerts_compute_success_update(
    *,
    alerts_id: str,
    artifact: AgentOutputArtifactPayload,
) -> JSONObject:
    return _guard_state_update(
        "alerts_compute",
        {
            "technical_analysis": {
                "alerts_id": alerts_id,
                "artifact": artifact,
            },
            "current_node": "alerts_compute",
            "internal_progress": {
                "alerts_compute": "done",
                "fusion_compute": "running",
            },
            "node_statuses": {"technical_analysis": "running"},
        },
    )


def build_fusion_compute_error_update(error_message: str) -> JSONObject:
    return _guard_state_update(
        "fusion_compute",
        {
            "current_node": "fusion_compute",
            "internal_progress": {"fusion_compute": "error"},
            "node_statuses": {"technical_analysis": "error"},
            "error_logs": [
                {
                    "node": "fusion_compute",
                    "error": error_message,
                    "severity": "error",
                }
            ],
        },
    )


def build_fusion_compute_success_update(
    *,
    fusion_report_id: str,
    confidence: float | None,
    artifact: AgentOutputArtifactPayload,
) -> JSONObject:
    return _guard_state_update(
        "fusion_compute",
        {
            "technical_analysis": {
                "fusion_report_id": fusion_report_id,
                "confidence": confidence,
                "artifact": artifact,
            },
            "current_node": "fusion_compute",
            "internal_progress": {
                "fusion_compute": "done",
                "verification_compute": "running",
            },
            "node_statuses": {"technical_analysis": "running"},
        },
    )


def build_verification_compute_error_update(error_message: str) -> JSONObject:
    return _guard_state_update(
        "verification_compute",
        {
            "current_node": "verification_compute",
            "internal_progress": {"verification_compute": "error"},
            "node_statuses": {"technical_analysis": "error"},
            "error_logs": [
                {
                    "node": "verification_compute",
                    "error": error_message,
                    "severity": "error",
                }
            ],
        },
    )


def build_verification_compute_success_update(
    *,
    verification_report_id: str,
    chart_data_id: str | None,
    latest_price: float | None,
    optimal_d: float | None,
    z_score_latest: float | None,
    window_length: int | None,
    adf_statistic: float | None,
    adf_pvalue: float | None,
    bollinger: JSONObject,
    statistical_strength_val: float | None,
    macd: JSONObject,
    obv: JSONObject,
    artifact: AgentOutputArtifactPayload,
) -> JSONObject:
    return _guard_state_update(
        "verification_compute",
        {
            "technical_analysis": {
                "verification_report_id": verification_report_id,
                "chart_data_id": chart_data_id,
                "latest_price": latest_price,
                "optimal_d": optimal_d,
                "z_score_latest": z_score_latest,
                "window_length": window_length,
                "adf_statistic": adf_statistic,
                "adf_pvalue": adf_pvalue,
                "bollinger": bollinger,
                "statistical_strength_val": statistical_strength_val,
                "macd": macd,
                "obv": obv,
                "artifact": artifact,
            },
            "current_node": "verification_compute",
            "internal_progress": {
                "verification_compute": "done",
                "semantic_translate": "running",
            },
            "node_statuses": {"technical_analysis": "running"},
        },
    )


def build_fracdiff_error_update(error_message: str) -> JSONObject:
    return _guard_state_update(
        "fracdiff_compute",
        {
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
        },
    )


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
    statistical_strength_val: float | None,
    macd: JSONObject,
    obv: JSONObject,
    artifact: AgentOutputArtifactPayload,
) -> JSONObject:
    return _guard_state_update(
        "fracdiff_compute",
        {
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
            "node_statuses": {"technical_analysis": "running"},
        },
    )


def build_semantic_success_update(
    ta_update: JSONObject,
    *,
    is_degraded: bool,
    degraded_reasons: list[str],
) -> SemanticCommandUpdateResult:
    technical_analysis = dict(ta_update)
    technical_analysis["is_degraded"] = is_degraded
    technical_analysis["degraded_reasons"] = list(degraded_reasons)
    return SemanticCommandUpdateResult(
        update=_guard_state_update(
            "semantic_translate",
            {
                "technical_analysis": technical_analysis,
                "current_node": "semantic_translate",
                "internal_progress": {"semantic_translate": "done"},
                "node_statuses": {"technical_analysis": "done"},
            },
        )
    )


def build_semantic_error_update(error_message: str) -> SemanticCommandUpdateResult:
    return SemanticCommandUpdateResult(
        update=_guard_state_update(
            "semantic_translate",
            {
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
            },
        )
    )


def _guard_state_update(node: str, update: JSONObject) -> JSONObject:
    violations = find_state_hygiene_violations(update)
    if not violations:
        return update

    log_event(
        logger,
        event="technical_state_hygiene_violation",
        message="technical state update rejected due to disallowed pandas payload",
        level=logging.ERROR,
        error_code="TECHNICAL_STATE_HYGIENE_VIOLATION",
        fields={
            "node": node,
            "violation_count": len(violations),
            "violations": violations,
        },
    )

    return {
        "current_node": node,
        "internal_progress": {node: "error"},
        "node_statuses": {"technical_analysis": "error"},
        "error_logs": [
            {
                "node": node,
                "error": (
                    "State payload contains disallowed pandas objects at: "
                    + ", ".join(violations)
                ),
                "severity": "error",
            }
        ],
    }
