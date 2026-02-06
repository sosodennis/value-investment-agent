from typing import Annotated

from langgraph.graph import add_messages
from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import NotRequired, TypedDict

from src.interface.schemas import AgentOutputArtifact

from ...state import (
    FundamentalAnalysisContext,
    IntentExtractionContext,
    append_logs,
    last_value,
    merge_dict,
)


class CalculatorInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    fundamental_analysis: FundamentalAnalysisContext
    intent_extraction: IntentExtractionContext | None = None


class CalculatorOutput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    fundamental_analysis: FundamentalAnalysisContext
    messages: list = Field(default_factory=list)
    node_statuses: dict[str, str]
    error_logs: list[dict]
    artifact: AgentOutputArtifact | None = None


class CalculatorState(TypedDict):
    ticker: NotRequired[str]
    intent_extraction: NotRequired[IntentExtractionContext]
    fundamental_analysis: Annotated[FundamentalAnalysisContext, merge_dict]
    messages: Annotated[list, add_messages]
    error_logs: Annotated[list[dict], append_logs]
    internal_progress: Annotated[dict[str, str], merge_dict]
    current_node: Annotated[str, last_value]
    node_statuses: Annotated[dict[str, str], merge_dict]
