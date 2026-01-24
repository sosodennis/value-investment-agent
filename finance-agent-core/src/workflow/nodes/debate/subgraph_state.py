"""
Isolated state class for Debate subgraph.
Following LangGraph best practices - does NOT share node_statuses with parent.
"""

from typing import Annotated

from pydantic import BaseModel, Field

from ...state import (
    DebateContext,
    FinancialNewsContext,
    FundamentalAnalysisContext,
    IntentExtractionContext,
    TechnicalAnalysisContext,
    last_value,
    merge_debate_context,
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
    fundamental: FundamentalAnalysisContext = Field(
        default_factory=FundamentalAnalysisContext
    )
    financial_news: FinancialNewsContext = Field(default_factory=FinancialNewsContext)
    technical_analysis: TechnicalAnalysisContext = Field(
        default_factory=TechnicalAnalysisContext
    )


class DebateOutput(BaseModel):
    """
    Output schema for debate subgraph.
    """

    debate: DebateContext
    model_type: str | None = None


class DebateState(BaseModel):
    """
    Internal state for debate subgraph.
    """

    # --- From Input ---
    ticker: str | None = None
    intent_extraction: IntentExtractionContext = Field(
        default_factory=IntentExtractionContext
    )
    fundamental: FundamentalAnalysisContext = Field(
        default_factory=FundamentalAnalysisContext
    )
    financial_news: FinancialNewsContext = Field(default_factory=FinancialNewsContext)
    technical_analysis: TechnicalAnalysisContext = Field(
        default_factory=TechnicalAnalysisContext
    )

    # --- Core State (Reducers applied) ---
    # Use Annotated with reducer to handle concurrent updates from Bull & Bear in Round 1
    debate: Annotated[DebateContext, merge_debate_context] = Field(
        default_factory=DebateContext
    )
    model_type: Annotated[str | None, last_value] = None

    # --- Private State ---
    internal_progress: Annotated[dict[str, str], merge_dict] = Field(
        default_factory=dict
    )
    current_node: Annotated[str, last_value] = ""
