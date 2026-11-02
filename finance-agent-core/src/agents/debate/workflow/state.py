"""State private to the debate subgraph plus shared root transport fields."""

from typing import Annotated

from langgraph.graph import add_messages
from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import TypedDict

from src.artifacts.public import ArtifactReferencePayload
from src.shared.cross_agent.domain.market_identity import CompanyProfile

DebateContext = dict[str, object]


def merge_dict(left: dict[str, object], right: dict[str, object]) -> dict[str, object]:
    return {**left, **right}


def last_value(_left: object, right: object) -> object:
    return right


def append_logs(
    left: list[dict[str, object]], right: list[dict[str, object]]
) -> list[dict[str, object]]:
    return [*left, *right]


class DebateInput(BaseModel):
    """Inputs shared with the root graph; debate state remains private."""

    model_config = ConfigDict(extra="ignore")

    company_profile: CompanyProfile | None = None
    artifact_references: dict[str, ArtifactReferencePayload] = Field(
        default_factory=dict
    )
    messages: list[object] = Field(default_factory=list)
    workflow_activity_statuses: dict[str, str] = Field(default_factory=dict)
    workflow_activity_updates: dict[str, str] = Field(default_factory=dict)
    active_activity_id: str | None = None
    error_logs: list[dict[str, object]] = Field(default_factory=list)


class DebateOutput(BaseModel):
    """
    Output schema for debate subgraph.
    """

    debate: DebateContext
    model_type: str | None = None
    messages: list[object] = Field(default_factory=list)
    company_profile: CompanyProfile | None = None
    artifact_references: dict[str, ArtifactReferencePayload] = Field(
        default_factory=dict
    )
    workflow_activity_statuses: dict[str, str] = Field(default_factory=dict)
    error_logs: list[dict] = Field(default_factory=list)


class DebateState(TypedDict):
    """
    Internal state for debate subgraph.
    Converted to TypedDict per Engineering Charter v3.1.
    """

    # --- Shared root transport ---
    company_profile: Annotated[CompanyProfile | None, last_value]
    artifact_references: Annotated[dict[str, ArtifactReferencePayload], merge_dict]

    # --- Core State (Reducers applied) ---
    # Use Annotated with reducer to handle concurrent updates from Bull & Bear in Round 1
    debate: Annotated[DebateContext, merge_dict]
    model_type: Annotated[str | None, last_value]
    messages: Annotated[list, add_messages]
    error_logs: Annotated[list[dict], append_logs]

    # Internal-only state during execution (removed from shared DebateContext)
    history: Annotated[list, add_messages]
    bull_thesis: Annotated[str | None, last_value]
    bear_thesis: Annotated[str | None, last_value]

    # --- Private State ---
    workflow_activity_updates: Annotated[dict[str, str], merge_dict]
    active_activity_id: Annotated[str, last_value]
    workflow_activity_statuses: Annotated[dict[str, str], merge_dict]
    context_summary_text: Annotated[str | None, last_value]
    facts_registry_text: Annotated[str | None, last_value]

    # Fact Registry (Grounding)
    facts_artifact_id: Annotated[str | None, last_value]
    facts_hash: Annotated[str | None, last_value]
    facts_summary: Annotated[dict | None, last_value]
    fact_extraction_status: Annotated[str | None, last_value]
