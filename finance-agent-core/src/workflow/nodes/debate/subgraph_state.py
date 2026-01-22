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


class DebateSubgraphState(BaseModel):
    """
    Isolated state for debate subgraph.

    This state is completely separate from the parent AgentState.
    It does NOT include node_statuses to prevent stale status updates.
    Uses Pydantic BaseModel to match parent AgentState structure.

    All fields that can be updated concurrently (Bull & Bear in Round 1) use reducers.
    """

    # Input from parent (required for debate logic)
    ticker: str | None
    intent_extraction: IntentExtractionContext  # Needed for resolved_ticker

    # Use Annotated with reducer to handle concurrent updates from Bull & Bear in Round 1
    debate: Annotated[DebateContext, merge_debate_context]

    fundamental: FundamentalAnalysisContext
    financial_news: FinancialNewsContext
    technical_analysis: TechnicalAnalysisContext

    # Model type (can be updated by moderator conclusion)
    model_type: str | None = None

    # Internal progress tracking (NOT shared with parent) - needs reducer for parallel updates
    internal_progress: Annotated[dict[str, str], merge_dict] = Field(
        default_factory=dict
    )

    # Current node tracking - needs reducer for parallel updates (last value wins)
    current_node: Annotated[str, last_value] = ""
