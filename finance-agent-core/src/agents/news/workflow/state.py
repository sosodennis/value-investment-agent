from __future__ import annotations

from typing import Annotated

from langgraph.graph import add_messages
from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import TypedDict

from src.artifacts.public import ArtifactReferencePayload
from src.shared.cross_agent.domain.market_identity import CompanyProfile

FinancialNewsContext = dict[str, object]


def merge_dict(left: dict[str, object], right: dict[str, object]) -> dict[str, object]:
    return {**left, **right}


def last_value(_left: object, right: object) -> object:
    return right


def append_logs(
    left: list[dict[str, object]], right: list[dict[str, object]]
) -> list[dict[str, object]]:
    return [*left, *right]


class FinancialNewsInput(BaseModel):
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


class FinancialNewsOutput(BaseModel):
    financial_news_research: FinancialNewsContext
    messages: list[object] = Field(default_factory=list)
    company_profile: CompanyProfile | None = None
    artifact_references: dict[str, ArtifactReferencePayload] = Field(
        default_factory=dict
    )
    workflow_activity_statuses: dict[str, str] = Field(default_factory=dict)
    error_logs: list[dict[str, object]] = Field(default_factory=list)


class FinancialNewsState(TypedDict):
    company_profile: Annotated[CompanyProfile | None, last_value]
    artifact_references: Annotated[dict[str, ArtifactReferencePayload], merge_dict]
    financial_news_research: Annotated[FinancialNewsContext, merge_dict]
    messages: Annotated[list, add_messages]
    workflow_activity_updates: Annotated[dict[str, str], merge_dict]
    active_activity_id: Annotated[str, last_value]
    workflow_activity_statuses: Annotated[dict[str, str], merge_dict]
    error_logs: Annotated[list[dict[str, object]], append_logs]
