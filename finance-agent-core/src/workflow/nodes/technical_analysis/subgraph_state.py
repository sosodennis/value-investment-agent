"""
Isolated state class for Technical Analysis subgraph.
Following LangGraph best practices - does NOT share node_statuses with parent.
"""

from typing import Annotated, NotRequired

from langgraph.graph import add_messages
from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import TypedDict

from ...state import (
    IntentExtractionContext,
    TechnicalAnalysisContext,
    append_logs,
    last_value,
    merge_dict,
)


class TechnicalAnalysisInput(BaseModel):
    """
    Input schema for technical analysis subgraph.
    """

    model_config = ConfigDict(extra="ignore")

    ticker: str | None = None
    intent_extraction: IntentExtractionContext = Field(default_factory=dict)
    technical_analysis: TechnicalAnalysisContext = Field(default_factory=dict)


class TechnicalAnalysisOutput(BaseModel):
    """
    Output schema for technical analysis subgraph.
    """

    technical_analysis: TechnicalAnalysisContext
    messages: list = Field(default_factory=list)
    node_statuses: dict[str, str] = Field(default_factory=dict)
    error_logs: list[dict] = Field(default_factory=list)


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
    error_logs: Annotated[list[dict], append_logs]

    # --- Private State ---
    internal_progress: Annotated[dict[str, str], merge_dict]
    current_node: Annotated[str, last_value]
    node_statuses: Annotated[dict[str, str], merge_dict]
