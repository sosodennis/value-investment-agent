from __future__ import annotations

from src.common.types import AgentOutputArtifactPayload, JSONObject


def build_financial_health_missing_ticker_update() -> JSONObject:
    return {
        "current_node": "financial_health",
        "internal_progress": {"financial_health": "error"},
        "error_logs": [
            {
                "node": "financial_health",
                "error": "No resolved ticker available",
                "severity": "error",
            }
        ],
    }


def build_financial_health_success_update(
    *,
    reports_artifact_id: str | None,
    artifact: AgentOutputArtifactPayload | None,
) -> JSONObject:
    fa_update: JSONObject = {
        "financial_reports_artifact_id": reports_artifact_id,
        "status": "model_selection",
    }
    if artifact is not None:
        fa_update["artifact"] = artifact

    return {
        "fundamental_analysis": fa_update,
        "current_node": "financial_health",
        "internal_progress": {
            "financial_health": "done",
            "model_selection": "running",
        },
        "node_statuses": {"fundamental_analysis": "running"},
    }


def build_model_selection_waiting_update() -> JSONObject:
    return {
        "fundamental_analysis": {"status": "clarifying"},
        "current_node": "model_selection",
        "internal_progress": {"model_selection": "waiting"},
    }


def build_model_selection_success_update(
    *,
    fa_update: JSONObject,
    resolved_ticker: str | None,
) -> JSONObject:
    update: JSONObject = {
        "fundamental_analysis": fa_update,
        "current_node": "model_selection",
        "internal_progress": {
            "model_selection": "done",
            "calculation": "running",
        },
        "node_statuses": {"fundamental_analysis": "running"},
    }
    if resolved_ticker is not None:
        update["ticker"] = resolved_ticker
    return update


def build_node_error_update(*, node: str, error: str) -> JSONObject:
    return {
        "error_logs": [
            {
                "node": node,
                "error": error,
                "severity": "error",
            }
        ],
        "internal_progress": {node: "error"},
        "node_statuses": {"fundamental_analysis": "error"},
    }
