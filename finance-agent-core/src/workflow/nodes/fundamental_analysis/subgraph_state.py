"""
Isolated state class for Fundamental Analysis subgraph.
Following LangGraph best practices - does NOT share node_statuses with parent.
"""

from typing import Annotated, NotRequired, TypedDict

from langgraph.graph import add_messages
from pydantic import BaseModel, Field

from ...state import (
    FundamentalAnalysisContext,
    IntentExtractionContext,
    last_value,
    merge_dict,
)


class FundamentalAnalysisInput(BaseModel):
    """
    Input schema for Fundamental Analysis subgraph.
    Defines the contract for what the parent graph must provide.
    """

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

    # --- Private State (Not exposed in FundamentalAnalysisOutput) ---
    internal_progress: Annotated[dict[str, str], merge_dict]
    current_node: Annotated[str, last_value]
    model_type: Annotated[str, last_value]
