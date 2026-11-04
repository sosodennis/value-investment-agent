from typing import Annotated, TypeAlias

from langgraph.graph import add_messages
from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import TypedDict

from src.artifacts.public import ArtifactReferencePayload
from src.shared.cross_agent.domain.market_identity import CompanyProfile

IntentExtractionContext: TypeAlias = dict[str, object]
FundamentalAnalysisContext: TypeAlias = dict[str, object]


def merge_dict(
    left: dict[str, object] | None, right: dict[str, object] | None
) -> dict[str, object]:
    if left is None:
        return right or {}
    if right is None:
        return left
    return {**left, **right}


def last_value(left: object | None, right: object | None) -> object | None:
    return right if right is not None else left


def append_logs(
    left: list[dict[str, object]] | None, right: list[dict[str, object]] | None
) -> list[dict[str, object]]:
    return (left or []) + (right or [])


class FundamentalAnalysisInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    company_profile: CompanyProfile | None = None
    valuation_request: dict[str, object] | None = None
    fundamental_analysis: FundamentalAnalysisContext = Field(default_factory=dict)
    artifact_references: dict[str, ArtifactReferencePayload] = Field(
        default_factory=dict
    )
    messages: list[object] = Field(default_factory=list)
    workflow_activity_statuses: dict[str, str] = Field(default_factory=dict)
    workflow_activity_updates: dict[str, str] = Field(default_factory=dict)
    active_activity_id: str | None = None
    error_logs: list[dict[str, object]] = Field(default_factory=list)


class FundamentalAnalysisOutput(BaseModel):
    fundamental_analysis: FundamentalAnalysisContext
    valuation_request: dict[str, object] | None = None
    messages: list[object] = Field(default_factory=list)
    company_profile: CompanyProfile | None = None
    artifact_references: dict[str, ArtifactReferencePayload] = Field(
        default_factory=dict
    )
    workflow_activity_statuses: dict[str, str] = Field(default_factory=dict)
    error_logs: list[dict[str, object]] = Field(default_factory=list)


class FundamentalAnalysisState(TypedDict):
    valuation_request: Annotated[dict[str, object] | None, last_value]
    company_profile: Annotated[CompanyProfile | None, last_value]
    artifact_references: Annotated[dict[str, ArtifactReferencePayload], merge_dict]
    fundamental_analysis: Annotated[FundamentalAnalysisContext, merge_dict]
    messages: Annotated[list[object], add_messages]
    error_logs: Annotated[list[dict[str, object]], append_logs]
    workflow_activity_updates: Annotated[dict[str, str], merge_dict]
    active_activity_id: Annotated[str | None, last_value]
    workflow_activity_statuses: Annotated[dict[str, str], merge_dict]


__all__ = [
    "FundamentalAnalysisContext",
    "FundamentalAnalysisInput",
    "FundamentalAnalysisOutput",
    "FundamentalAnalysisState",
    "IntentExtractionContext",
]
