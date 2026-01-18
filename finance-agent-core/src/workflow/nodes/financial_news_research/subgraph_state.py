"""
Isolated state class for Financial News Research subgraph.
Following LangGraph best practices - does NOT share node_statuses with parent.
"""

from typing import Annotated

from pydantic import BaseModel, Field

from ...state import (
    FinancialNewsContext,
    IntentExtractionContext,
    last_value,
    merge_dict,
    merge_financial_news_context,
)


class FinancialNewsSubgraphState(BaseModel):
    """
    Isolated state for financial news research subgraph.

    This state is completely separate from the parent AgentState.
    It does NOT include node_statuses to prevent stale status updates.
    Uses Pydantic BaseModel to match parent AgentState structure.
    """

    # Input from parent
    ticker: str | None
    intent_extraction: IntentExtractionContext  # Needed for resolved_ticker
    financial_news: Annotated[FinancialNewsContext, merge_financial_news_context]

    # Internal progress tracking (NOT shared with parent)
    internal_progress: Annotated[dict[str, str], merge_dict] = Field(
        default_factory=dict
    )

    # Current node tracking
    current_node: Annotated[str, last_value] = ""
