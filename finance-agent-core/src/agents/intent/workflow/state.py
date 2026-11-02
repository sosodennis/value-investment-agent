from __future__ import annotations

from typing import Annotated, NotRequired

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages
from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import TypedDict

from src.artifacts.public import AgentOutputArtifactPayload, ArtifactReferencePayload
from src.shared.cross_agent.domain.market_identity import CompanyProfile
from src.shared.kernel.types import JSONObject


class IntentExtractionContext(TypedDict):
    extracted_intent: NotRequired[JSONObject | None]
    ticker_candidates: NotRequired[list[JSONObject] | None]
    resolved_ticker: NotRequired[str | None]
    company_profile: NotRequired[JSONObject | None]
    status: NotRequired[str | None]
    artifact: NotRequired[AgentOutputArtifactPayload | None]


def merge_dict(
    left: dict[str, object] | None, right: dict[str, object] | None
) -> dict[str, object]:
    return {**(left or {}), **(right or {})}


def last_value(left: object | None, right: object | None) -> object | None:
    return right if right is not None else left


def append_logs(
    left: list[dict[str, object]] | None, right: list[dict[str, object]] | None
) -> list[dict[str, object]]:
    return (left or []) + (right or [])


class IntentExtractionInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_query: str | None = None
    messages: list[AnyMessage] = Field(default_factory=list)
    workflow_activity_statuses: dict[str, str] = Field(default_factory=dict)
    workflow_activity_updates: dict[str, str] = Field(default_factory=dict)
    active_activity_id: str | None = None
    error_logs: list[dict[str, object]] = Field(default_factory=list)


class IntentExtractionOutput(BaseModel):
    intent_extraction: IntentExtractionContext
    messages: list[AnyMessage] = Field(default_factory=list)
    company_profile: CompanyProfile | None = None
    artifact_references: dict[str, ArtifactReferencePayload] = Field(
        default_factory=dict
    )
    workflow_activity_statuses: dict[str, str] = Field(default_factory=dict)
    error_logs: list[dict[str, object]] = Field(default_factory=list)


class IntentExtractionState(TypedDict):
    user_query: str | None
    intent_extraction: Annotated[IntentExtractionContext, merge_dict]
    messages: Annotated[list[AnyMessage], add_messages]
    company_profile: Annotated[CompanyProfile | None, last_value]
    artifact_references: Annotated[dict[str, ArtifactReferencePayload], merge_dict]
    workflow_activity_updates: Annotated[dict[str, str], merge_dict]
    active_activity_id: Annotated[str, last_value]
    workflow_activity_statuses: Annotated[dict[str, str], merge_dict]
    error_logs: Annotated[list[dict[str, object]], append_logs]
