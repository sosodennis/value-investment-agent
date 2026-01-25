"""
Isolated state class for Debate subgraph.
Following LangGraph best practices - does NOT share node_statuses with parent.
"""

from typing import Annotated

from langgraph.graph import add_messages
from pydantic import BaseModel, Field

from src.interface.schemas import AgentOutputArtifact

from ...state import (
    DebateContext,
    FinancialNewsContext,
    FundamentalAnalysisContext,
    IntentExtractionContext,
    TechnicalAnalysisContext,
    create_pydantic_reducer,
    last_value,
    merge_dict,
)


class DebateInput(BaseModel):
    """
    Input schema for debate subgraph.
    """

    ticker: str | None = None
    intent_extraction: IntentExtractionContext = Field(
        default_factory=IntentExtractionContext
    )
    debate: DebateContext = Field(default_factory=DebateContext)
    fundamental_analysis: FundamentalAnalysisContext = Field(
        default_factory=FundamentalAnalysisContext
    )
    financial_news_research: FinancialNewsContext = Field(
        default_factory=FinancialNewsContext
    )
    technical_analysis: TechnicalAnalysisContext = Field(
        default_factory=TechnicalAnalysisContext
    )


class DebateOutput(BaseModel):
    """
    Output schema for debate subgraph.
    """

    debate: DebateContext
    model_type: str | None = None
    artifact: AgentOutputArtifact | None = None
    messages: list = Field(default_factory=list)


class DebateState(BaseModel):
    """
    Internal state for debate subgraph.
    """

    # --- From Input ---
    ticker: str | None = None
    intent_extraction: IntentExtractionContext = Field(
        default_factory=IntentExtractionContext
    )
    fundamental_analysis: FundamentalAnalysisContext = Field(
        default_factory=FundamentalAnalysisContext
    )
    financial_news_research: FinancialNewsContext = Field(
        default_factory=FinancialNewsContext
    )
    technical_analysis: TechnicalAnalysisContext = Field(
        default_factory=TechnicalAnalysisContext
    )

    # --- Core State (Reducers applied) ---
    # Use Annotated with reducer to handle concurrent updates from Bull & Bear in Round 1
    debate: Annotated[DebateContext, create_pydantic_reducer(DebateContext)] = Field(
        default_factory=DebateContext
    )
    model_type: Annotated[str | None, last_value] = None

    # --- Output (Direct in State layer for Flat Pattern) ---
    artifact: AgentOutputArtifact | None = None
    messages: Annotated[list, add_messages] = Field(default_factory=list)

    # --- Private State ---
    internal_progress: Annotated[dict[str, str], merge_dict] = Field(
        default_factory=dict
    )
    current_node: Annotated[str, last_value] = ""
