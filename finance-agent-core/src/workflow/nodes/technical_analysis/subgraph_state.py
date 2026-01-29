"""
Isolated state class for Technical Analysis subgraph.
Following LangGraph best practices - does NOT share node_statuses with parent.
"""

from typing import Annotated, NotRequired, TypedDict

from langgraph.graph import add_messages
from pydantic import BaseModel, Field

from ...state import (
    IntentExtractionContext,
    TechnicalAnalysisContext,
    last_value,
    merge_dict,
)


class TechnicalAnalysisInput(BaseModel):
    """
    Input schema for technical analysis subgraph.
    """

    ticker: str | None = None
    intent_extraction: IntentExtractionContext = Field(default_factory=dict)
    technical_analysis: TechnicalAnalysisContext = Field(default_factory=dict)


class TechnicalAnalysisOutput(BaseModel):
    """
    Output schema for technical analysis subgraph.
    """

    technical_analysis: TechnicalAnalysisContext
    messages: list = Field(default_factory=list)


class TechnicalAnalysisState(TypedDict):
    """
    Internal state for technical analysis subgraph.
    Converted to TypedDict per Engineering Charter v3.1.
    """

    # --- From Input ---
    ticker: NotRequired[str | None]
    intent_extraction: NotRequired[IntentExtractionContext]

    # --- Core State (Reducers applied) ---
    technical_analysis: Annotated[TechnicalAnalysisContext, merge_dict]
    messages: Annotated[list, add_messages]

    # --- Private State ---
    internal_progress: Annotated[dict[str, str], merge_dict]
    current_node: Annotated[str, last_value]
