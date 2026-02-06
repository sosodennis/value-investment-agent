"""
Isolated state class for Debate subgraph.
Following LangGraph best practices - does NOT share node_statuses with parent.
"""

from typing import Annotated, NotRequired

from langgraph.graph import add_messages
from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import TypedDict

from ...state import (
    DebateContext,
    FinancialNewsContext,
    FundamentalAnalysisContext,
    IntentExtractionContext,
    TechnicalAnalysisContext,
    append_logs,
    last_value,
    merge_dict,
)


class DebateInput(BaseModel):
    """
    Input schema for debate subgraph.
    """

    model_config = ConfigDict(extra="ignore")

    ticker: str | None = None
    intent_extraction: IntentExtractionContext = Field(default_factory=dict)
    debate: DebateContext = Field(default_factory=dict)
    fundamental_analysis: FundamentalAnalysisContext = Field(default_factory=dict)
    financial_news_research: FinancialNewsContext = Field(default_factory=dict)
    technical_analysis: TechnicalAnalysisContext = Field(default_factory=dict)


class DebateOutput(BaseModel):
    """
    Output schema for debate subgraph.
    """

    debate: DebateContext
    model_type: str | None = None
    messages: list = Field(default_factory=list)
    node_statuses: dict[str, str] = Field(default_factory=dict)
    error_logs: list[dict] = Field(default_factory=list)


class DebateState(TypedDict):
    """
    Internal state for debate subgraph.
    Converted to TypedDict per Engineering Charter v3.1.
    """

    # --- From Input ---
    ticker: NotRequired[str | None]
    intent_extraction: NotRequired[IntentExtractionContext]
    fundamental_analysis: NotRequired[FundamentalAnalysisContext]
    financial_news_research: NotRequired[FinancialNewsContext]
    technical_analysis: NotRequired[TechnicalAnalysisContext]

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
    internal_progress: Annotated[dict[str, str], merge_dict]
    current_node: Annotated[str, last_value]
    compressed_reports: Annotated[str | None, last_value]
