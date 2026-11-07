from __future__ import annotations

from src.artifacts.public import AgentOutputArtifactPayload
from src.shared.kernel.types import JSONObject


def build_financial_health_missing_ticker_update() -> JSONObject:
    return {
        "active_activity_id": "financial_health",
        "workflow_activity_updates": {"financial_health": "error"},
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
    artifact: AgentOutputArtifactPayload | None,
    diagnostics: JSONObject | None = None,
    quality_gates: JSONObject | None = None,
) -> JSONObject:
    fa_update: JSONObject = {
        "service_snapshot_status": "unavailable",
    }
    if diagnostics is not None:
        fa_update["xbrl_diagnostics"] = diagnostics
    if quality_gates is not None:
        fa_update["xbrl_quality_gates"] = quality_gates
    if artifact is not None:
        fa_update["artifact"] = artifact

    update: JSONObject = {
        "fundamental_analysis": fa_update,
        "active_activity_id": "financial_health",
        "workflow_activity_updates": {
            "financial_health": "done",
            "model_selection": "running",
        },
    }
    return update


def build_model_selection_waiting_update() -> JSONObject:
    return {
        "active_activity_id": "model_selection",
        "workflow_activity_updates": {"model_selection": "waiting"},
    }


def build_model_selection_success_update(
    *,
    fa_update: JSONObject,
) -> JSONObject:
    update: JSONObject = {
        "fundamental_analysis": fa_update,
        "active_activity_id": "model_selection",
        "workflow_activity_updates": {
            "model_selection": "done",
            "calculation": "running",
        },
    }
    return update


def build_node_error_update(*, node: str, error: str) -> JSONObject:
    return {
        "active_activity_id": node,
        "error_logs": [
            {
                "node": node,
                "error": error,
                "severity": "error",
            }
        ],
        "workflow_activity_updates": {node: "error"},
    }
