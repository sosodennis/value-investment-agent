from __future__ import annotations

from typing import Literal, TypeAlias

from typing_extensions import TypedDict

from src.shared.kernel.types import JSONObject

BoundaryContractKind: TypeAlias = Literal[
    "workflow_state",
    "artifact_json",
    "interrupt_payload",
]

CONTRACT_KIND_WORKFLOW_STATE: BoundaryContractKind = "workflow_state"
CONTRACT_KIND_ARTIFACT_JSON: BoundaryContractKind = "artifact_json"
CONTRACT_KIND_INTERRUPT_PAYLOAD: BoundaryContractKind = "interrupt_payload"


class BoundaryReplayDiagnostics(TypedDict):
    node: str
    current_node: str | None
    ticker: str | None
    message_count: int
    artifact_refs: dict[str, str]
    node_statuses: dict[str, str]
    internal_progress: dict[str, str]


class BoundaryEventPayload(TypedDict, total=False):
    node: str
    artifact_id: str | None
    contract_kind: BoundaryContractKind
    error_code: str
    detail: JSONObject
    replay: BoundaryReplayDiagnostics
