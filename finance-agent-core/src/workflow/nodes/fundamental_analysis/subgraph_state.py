"""
Isolated state class for Fundamental Analysis subgraph.
Shared node_statuses with parent.
"""

from typing import Annotated, NotRequired

from langgraph.graph import add_messages
from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import TypedDict

from ...state import (
    FundamentalAnalysisContext,
    IntentExtractionContext,
    append_logs,
    last_value,
    merge_dict,
)


class FundamentalAnalysisInput(BaseModel):
    """
    Input schema for Fundamental Analysis subgraph.
    Defines the contract for what the parent graph must provide.
    """

    model_config = ConfigDict(extra="ignore")

    ticker: str | None = None
    intent_extraction: IntentExtractionContext = Field(default_factory=dict)
    fundamental_analysis: FundamentalAnalysisContext = Field(default_factory=dict)


class FundamentalAnalysisOutput(BaseModel):
    """
    Output schema for Fundamental Analysis subgraph.
    Defines exactly what fields are returned to the parent state.
    """

    fundamental_analysis: FundamentalAnalysisContext
    messages: list = Field(default_factory=list)
    node_statuses: dict[str, str] = Field(default_factory=dict)
    error_logs: list[dict] = Field(default_factory=list)


class FundamentalAnalysisState(TypedDict):
    """
    Internal state for fundamental analysis subgraph.
    Combines input fields, output fields, and private state.
    Refactored to TypedDict per Engineering Charter v3.1.
    """

    # --- From Input ---
    ticker: NotRequired[str | None]
    intent_extraction: NotRequired[IntentExtractionContext]

    # --- Core State (Reducers applied) ---
    fundamental_analysis: Annotated[FundamentalAnalysisContext, merge_dict]
    messages: Annotated[list, add_messages]
    error_logs: Annotated[list[dict], append_logs]

    # --- Private State (Not exposed in FundamentalAnalysisOutput) ---
    internal_progress: Annotated[dict[str, str], merge_dict]
    current_node: Annotated[str, last_value]
    node_statuses: Annotated[dict[str, str], merge_dict]
