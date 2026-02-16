from __future__ import annotations

import json
import logging
from collections.abc import Mapping

from src.shared.kernel.types import JSONObject

CONTRACT_KIND_WORKFLOW_STATE = "workflow_state"
CONTRACT_KIND_ARTIFACT_JSON = "artifact_json"
CONTRACT_KIND_INTERRUPT_PAYLOAD = "interrupt_payload"


def _is_artifact_ref_key(key: str) -> bool:
    return key.endswith("_artifact_id") or key in {
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


def build_replay_diagnostics(state: Mapping[str, object], *, node: str) -> JSONObject:
    messages = state.get("messages")
    message_count = len(messages) if isinstance(messages, list) else 0

    replay: JSONObject = {
        "node": node,
        "current_node": (
            state.get("current_node")
            if isinstance(state.get("current_node"), str)
            else None
        ),
        "ticker": state.get("ticker") if isinstance(state.get("ticker"), str) else None,
        "message_count": message_count,
        "artifact_refs": _collect_artifact_refs(state),
        "node_statuses": _string_map(state.get("node_statuses")),
        "internal_progress": _string_map(state.get("internal_progress")),
    }
    return replay


def log_boundary_event(
    logger: logging.Logger,
    *,
    node: str,
    artifact_id: str | None,
    contract_kind: str,
    error_code: str,
    state: Mapping[str, object] | None = None,
    detail: JSONObject | None = None,
    level: int = logging.INFO,
) -> JSONObject:
    payload: JSONObject = {
        "node": node,
        "artifact_id": artifact_id,
        "contract_kind": contract_kind,
        "error_code": error_code,
    }
    if detail is not None:
        payload["detail"] = detail
    if state is not None:
        payload["replay"] = build_replay_diagnostics(state, node=node)

    logger.log(
        level,
        "BOUNDARY_EVENT %s",
        json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str),
    )
    return payload
