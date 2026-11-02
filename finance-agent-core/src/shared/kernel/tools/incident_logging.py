from __future__ import annotations

import json
import logging
from collections.abc import Mapping

from src.shared.cross_agent.domain.market_identity import CompanyProfile
from src.shared.kernel.boundary_contracts import (
    CONTRACT_KIND_ARTIFACT_JSON,
    CONTRACT_KIND_INTERRUPT_PAYLOAD,
    CONTRACT_KIND_WORKFLOW_STATE,
    BoundaryContractKind,
    BoundaryEventPayload,
    BoundaryReplayDiagnostics,
)
from src.shared.kernel.tools.logger import log_event
from src.shared.kernel.types import JSONObject

__all__ = [
    "CONTRACT_KIND_WORKFLOW_STATE",
    "CONTRACT_KIND_ARTIFACT_JSON",
    "CONTRACT_KIND_INTERRUPT_PAYLOAD",
    "build_replay_diagnostics",
    "log_boundary_event",
]


def _is_artifact_ref_key(key: str) -> bool:
    return key.endswith("_artifact_id") or key in {
        "artifact_id",
        "report_id",
        "transcript_id",
        "chart_data_id",
    }


def _collect_artifact_refs(
    payload: Mapping[str, object], *, prefix: str = ""
) -> dict[str, str]:
    refs: dict[str, str] = {}
    for key, value in payload.items():
        if isinstance(value, Mapping):
            refs.update(_collect_artifact_refs(value, prefix=f"{prefix}{key}."))
            continue
        if _is_artifact_ref_key(key) and isinstance(value, str) and value.strip():
            refs[f"{prefix}{key}"] = value
    return refs


def _string_map(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    output: dict[str, str] = {}
    for key, val in value.items():
        if isinstance(key, str) and isinstance(val, str):
            output[key] = val
    return output


def _resolved_ticker_from_state(state: Mapping[str, object]) -> str | None:
    profile_raw = state.get("company_profile")
    if isinstance(profile_raw, CompanyProfile):
        resolved_ticker = profile_raw.ticker
    elif isinstance(profile_raw, Mapping):
        resolved_ticker = profile_raw.get("ticker")
    else:
        return None
    if isinstance(resolved_ticker, str) and resolved_ticker.strip():
        return resolved_ticker
    return None


def build_replay_diagnostics(
    state: Mapping[str, object], *, node: str
) -> BoundaryReplayDiagnostics:
    messages = state.get("messages")
    message_count = len(messages) if isinstance(messages, list) else 0

    replay: BoundaryReplayDiagnostics = {
        "node": node,
        "active_activity_id": (
            state.get("active_activity_id")
            if isinstance(state.get("active_activity_id"), str)
            else None
        ),
        "ticker": _resolved_ticker_from_state(state),
        "message_count": message_count,
        "artifact_refs": _collect_artifact_refs(state),
        "workflow_activity_statuses": _string_map(
            state.get("workflow_activity_statuses")
        ),
        "workflow_activity_updates": _string_map(
            state.get("workflow_activity_updates")
        ),
    }
    return replay


def log_boundary_event(
    logger: logging.Logger,
    *,
    node: str,
    artifact_id: str | None,
    contract_kind: BoundaryContractKind,
    error_code: str,
    state: Mapping[str, object] | None = None,
    detail: JSONObject | None = None,
    level: int = logging.INFO,
) -> BoundaryEventPayload:
    payload: BoundaryEventPayload = {
        "node": node,
        "artifact_id": artifact_id,
        "contract_kind": contract_kind,
        "error_code": error_code,
    }
    if detail is not None:
        payload["detail"] = detail
    if state is not None:
        payload["replay"] = build_replay_diagnostics(state, node=node)

    log_event(
        logger,
        event="BOUNDARY_EVENT",
        message="boundary_event",
        level=level,
        error_code=error_code,
        fields={
            "payload": json.loads(
                json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
            )
        },
    )
    return payload
