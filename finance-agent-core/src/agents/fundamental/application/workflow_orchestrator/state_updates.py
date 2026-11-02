from __future__ import annotations

from src.artifacts.public import (
    ARTIFACT_KIND_FINANCIAL_REPORTS,
    AgentOutputArtifactPayload,
    ArtifactReference,
    to_artifact_reference_payload,
)
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
    reports_artifact_id: str | None,
    artifact: AgentOutputArtifactPayload | None,
    diagnostics: JSONObject | None = None,
    quality_gates: JSONObject | None = None,
) -> JSONObject:
    fa_update: JSONObject = {
        "financial_reports_artifact_id": reports_artifact_id,
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
    if reports_artifact_id:
        update["artifact_references"] = {
            "financial_reports": to_artifact_reference_payload(
                ArtifactReference(
                    artifact_id=reports_artifact_id,
                    download_url=f"/api/v1/artifacts/{reports_artifact_id}",
                    type=ARTIFACT_KIND_FINANCIAL_REPORTS,
                )
            )
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
    artifact_id = fa_update.get("financial_reports_artifact_id")
    if isinstance(artifact_id, str) and artifact_id:
        update["artifact_references"] = {
            "financial_reports": to_artifact_reference_payload(
                ArtifactReference(
                    artifact_id=artifact_id,
                    download_url=f"/api/v1/artifacts/{artifact_id}",
                    type=ARTIFACT_KIND_FINANCIAL_REPORTS,
                )
            )
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
