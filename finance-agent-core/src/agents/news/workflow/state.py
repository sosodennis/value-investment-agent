from __future__ import annotations

from typing import Annotated, NotRequired

from langgraph.graph import add_messages
from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import TypedDict

FinancialNewsContext = dict[str, object]
IntentExtractionContext = dict[str, object]


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

    intent_extraction: IntentExtractionContext = Field(default_factory=dict)
    financial_news_research: FinancialNewsContext = Field(default_factory=dict)


class FinancialNewsOutput(BaseModel):
    financial_news_research: FinancialNewsContext
    messages: list[object] = Field(default_factory=list)
    node_statuses: dict[str, str] = Field(default_factory=dict)
    error_logs: list[dict[str, object]] = Field(default_factory=list)


class FinancialNewsState(TypedDict):
    intent_extraction: NotRequired[IntentExtractionContext]
    financial_news_research: Annotated[FinancialNewsContext, merge_dict]
    messages: Annotated[list, add_messages]
    internal_progress: Annotated[dict[str, str], merge_dict]
    current_node: Annotated[str, last_value]
    node_statuses: Annotated[dict[str, str], merge_dict]
    error_logs: Annotated[list[dict[str, object]], append_logs]
