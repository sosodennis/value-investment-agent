from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_AGENT_OUTPUT_PREVIEW_BYTES = 16 * 1024

ActivityStatus = Literal[
    "queued",
    "running",
    "waiting",
    "completed",
    "failed",
    "cancelled",
    "skipped",
]
ActivityKind = Literal["phase", "node", "tool", "subgraph"]
RunStatus = Literal[
    "queued",
    "running",
    "waiting",
    "completed",
    "failed",
    "cancelled",
    "unknown",
]
RetryStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
_RETRY_TRANSITIONS: dict[RetryStatus, frozenset[RetryStatus]] = {
    "queued": frozenset({"queued", "running", "cancelled"}),
    "running": frozenset({"running", "completed", "failed", "cancelled"}),
    "completed": frozenset({"completed"}),
    "failed": frozenset({"failed"}),
    "cancelled": frozenset({"cancelled"}),
}


class CheckpointIdentity(BaseModel):
    """The exact durable graph boundary selected for a recovery attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    namespace: str = Field(default="", max_length=240)
    checkpoint_id: str = Field(min_length=1, max_length=240)
    activity_id: str | None = Field(default=None, min_length=1, max_length=200)


class WorkflowFailure(BaseModel):
    """Safe, stable failure details exposed by the owning runtime."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=120)
    owner: str = Field(min_length=1, max_length=160)
    activity_id: str | None = Field(default=None, min_length=1, max_length=200)
    retryable: bool
    message: str = Field(min_length=1, max_length=500)
    checkpoint: CheckpointIdentity | None = None


class TickerCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=160)
    exchange: str | None = None
    type: str | None = None
    confidence: float = Field(ge=0, le=1)


class TickerSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["ticker_selection"]
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=500)
    candidates: list[TickerCandidate] = Field(min_length=1, max_length=20)


class TickerSelectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["ticker_selection"]
    selected_symbol: str = Field(min_length=1, max_length=32)


class ValuationApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["valuation_approval"]
    contract_version: Literal["v1"]
    ticker: str = Field(min_length=1, max_length=32)
    model_type: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=500)
    parameters: dict[str, object]
    audit_messages: list[str] = Field(max_length=100)

    @model_validator(mode="after")
    def bound_parameters(self) -> ValuationApprovalRequest:
        try:
            size = len(
                json.dumps(
                    self.parameters,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "approval parameters must contain finite JSON values"
            ) from exc
        if size > MAX_AGENT_OUTPUT_PREVIEW_BYTES:
            raise ValueError("approval parameters exceed 16 KiB")
        return self


class ValuationApprovalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["valuation_approval"]
    contract_version: Literal["v1"]
    decision: Literal["approve", "reject"]


InteractionRequest = Annotated[
    TickerSelectionRequest | ValuationApprovalRequest,
    Field(discriminator="type"),
]
InteractionResponse = Annotated[
    TickerSelectionResponse | ValuationApprovalResponse,
    Field(discriminator="type"),
]


class WorkflowActivityIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    activity_id: str = Field(min_length=1)


class InteractionIdentity(WorkflowActivityIdentity):
    interaction_id: str = Field(min_length=1, max_length=200)


class Activity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity_id: str = Field(min_length=1)
    parent_activity_id: str | None = Field(default=None, min_length=1)
    thread_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    scope_path: tuple[str, ...] = Field(min_length=1)
    kind: ActivityKind
    status: ActivityStatus
    label: str = Field(min_length=1, max_length=160)
    progress: float | None = Field(default=None, ge=0, le=100)
    attempt: int = Field(ge=1)
    failure: WorkflowFailure | None = None

    @model_validator(mode="after")
    def validate_failure(self) -> Activity:
        if self.failure is not None and self.status != "failed":
            raise ValueError("failure details require a failed activity")
        return self


class InteractionRequested(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity: Activity
    identity: InteractionIdentity
    request: InteractionRequest

    @model_validator(mode="after")
    def validate_identity(self) -> InteractionRequested:
        if self.activity.status != "waiting":
            raise ValueError("requested interactions require a waiting activity")
        if (
            self.activity.thread_id,
            self.activity.run_id,
            self.activity.activity_id,
        ) != (
            self.identity.thread_id,
            self.identity.run_id,
            self.identity.activity_id,
        ):
            raise ValueError("interaction and activity identity must match")
        return self


class WorkflowInteraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity: InteractionIdentity
    kind: Literal["ticker_selection", "valuation_approval"]
    status: Literal["pending", "responded", "cancelled"]
    request: InteractionRequest
    response: InteractionResponse | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> WorkflowInteraction:
        if (self.status == "responded") != (self.response is not None):
            raise ValueError("only a responded interaction may carry a response")
        if self.kind != self.request.type:
            raise ValueError("interaction kind must match its request type")
        if self.response is not None:
            if self.response.type != self.request.type:
                raise ValueError("response type must match its request type")
            if (
                isinstance(self.request, TickerSelectionRequest)
                and isinstance(self.response, TickerSelectionResponse)
                and self.response.selected_symbol
                not in {candidate.symbol for candidate in self.request.candidates}
            ):
                raise ValueError("response must select one of the stored candidates")
        return self


class WorkflowAgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity: WorkflowActivityIdentity
    agent_id: str = Field(min_length=1, max_length=120)
    output_kind: str = Field(min_length=1, max_length=120)
    output_version: str = Field(min_length=1, max_length=40)
    summary: str = Field(min_length=1, max_length=2000)
    preview: dict[str, object] | None = None
    artifact_id: str | None = Field(default=None, min_length=1, max_length=200)
    artifact_type: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def bound_preview(self) -> WorkflowAgentOutput:
        if self.preview is None:
            return self
        try:
            size = len(
                json.dumps(
                    self.preview,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("preview must contain only finite JSON values") from exc
        if size > 16 * 1024:
            raise ValueError("serialized preview exceeds 16 KiB")
        return self


class ActivityEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1)
    seq_id: int = Field(ge=1)
    event_version: Literal["v2"] = "v2"
    event_name: Literal["workflow.activity"] = "workflow.activity"
    thread_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    occurred_at: datetime
    payload: Activity

    @model_validator(mode="after")
    def validate_identity(self) -> ActivityEvent:
        if (self.thread_id, self.run_id) != (
            self.payload.thread_id,
            self.payload.run_id,
        ):
            raise ValueError("activity event and payload identity must match")
        return self


class WorkflowInteractionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1)
    seq_id: int = Field(ge=1)
    event_version: Literal["v1"] = "v1"
    event_name: Literal["workflow.interaction"] = "workflow.interaction"
    thread_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    occurred_at: datetime
    payload: WorkflowInteraction

    @model_validator(mode="after")
    def validate_identity(self) -> WorkflowInteractionEvent:
        if (self.thread_id, self.run_id) != (
            self.payload.identity.thread_id,
            self.payload.identity.run_id,
        ):
            raise ValueError("interaction event and payload identity must match")
        return self


class WorkflowAgentOutputEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1)
    seq_id: int = Field(ge=1)
    event_version: Literal["v1"] = "v1"
    event_name: Literal["workflow.agent_output"] = "workflow.agent_output"
    thread_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    occurred_at: datetime
    payload: WorkflowAgentOutput

    @model_validator(mode="after")
    def validate_identity(self) -> WorkflowAgentOutputEvent:
        if (self.thread_id, self.run_id) != (
            self.payload.identity.thread_id,
            self.payload.identity.run_id,
        ):
            raise ValueError("output event and payload identity must match")
        return self


WorkflowEvent = Annotated[
    ActivityEvent | WorkflowInteractionEvent | WorkflowAgentOutputEvent,
    Field(discriminator="event_name"),
]


class PendingResume(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity: InteractionIdentity
    principal_id: str
    organization_id: str = "unscoped"
    membership_id: str = "unscoped"
    response: InteractionResponse
    scope_path: tuple[str, ...] = Field(min_length=1)
    attempt: int = Field(ge=1)


class ClaimedInteractionResume(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity: InteractionIdentity
    organization_id: str = "unscoped"
    membership_id: str = "unscoped"
    response: InteractionResponse
    scope_path: tuple[str, ...] = Field(min_length=1)
    attempt: int = Field(ge=1)
    events: tuple[WorkflowEvent, ...]


class RunStatusRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    run_id: str
    principal_id: str = "unscoped"
    organization_id: str = "unscoped"
    membership_id: str = "unscoped"
    status: RunStatus
    started_at: datetime
    updated_at: datetime
    ended_at: datetime | None = None


class AnalysisRunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    run_id: str
    principal_id: str = "unscoped"
    organization_id: str = "unscoped"
    membership_id: str = "unscoped"
    status: RunStatus
    started_at: datetime | None = None
    updated_at: datetime | None = None
    ended_at: datetime | None = None
    input_data: dict[str, object] | None = None
    source_run_id: str | None = None
    retry_operation_id: str | None = None
    attempt: int = Field(default=1, ge=1)
    checkpoint: CheckpointIdentity | None = None


class AnalysisRunPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runs: tuple[AnalysisRunRecord, ...]
    has_more: bool
    next_started_at: datetime | None = None
    next_thread_id: str | None = None
    next_run_id: str | None = None


class RetryOperation(BaseModel):
    """Durable command record linking one immutable failure to one retry run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str = Field(min_length=1, max_length=120)
    thread_id: str = Field(min_length=1)
    source_run_id: str = Field(min_length=1)
    target_run_id: str = Field(min_length=1)
    principal_id: str = Field(min_length=1)
    organization_id: str = "unscoped"
    membership_id: str = "unscoped"
    idempotency_key: str = Field(min_length=1, max_length=200)
    request_hash: str = Field(min_length=64, max_length=64)
    checkpoint: CheckpointIdentity
    attempt: int = Field(ge=1)
    status: RetryStatus
    outcome: str | None = Field(default=None, max_length=500)
    created_at: datetime
    updated_at: datetime
    ended_at: datetime | None = None

    def can_transition_to(self, status: str) -> bool:
        return status in _RETRY_TRANSITIONS[self.status]


class RetryOperationView(BaseModel):
    """Safe retry state projection for workflow snapshots."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str = Field(min_length=1, max_length=120)
    thread_id: str = Field(min_length=1)
    source_run_id: str = Field(min_length=1)
    target_run_id: str = Field(min_length=1)
    checkpoint: CheckpointIdentity
    attempt: int = Field(ge=1)
    status: RetryStatus
    outcome: str | None = Field(default=None, max_length=500)
    created_at: datetime
    updated_at: datetime
    ended_at: datetime | None = None

    @classmethod
    def from_operation(cls, operation: RetryOperation) -> RetryOperationView:
        return cls.model_validate(
            operation.model_dump(
                exclude={
                    "principal_id",
                    "organization_id",
                    "membership_id",
                    "idempotency_key",
                    "request_hash",
                }
            )
        )


class RetryCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["v1"]
    checkpoint: CheckpointIdentity


class WorkflowSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    run_id: str
    run_status: RunStatus
    cursor: int = Field(ge=0)
    active_activities: tuple[Activity, ...] = ()
    recent_activities: tuple[Activity, ...] = ()
    pending_interactions: tuple[WorkflowInteraction, ...] = ()
    completed_outputs: tuple[WorkflowAgentOutput, ...] = ()
    failure: WorkflowFailure | None = None
    retry_operation: RetryOperationView | None = None


class ReplayPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: tuple[WorkflowEvent, ...]
    cursor: int
    has_more: bool
