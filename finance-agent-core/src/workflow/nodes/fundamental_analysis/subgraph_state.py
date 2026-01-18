"""
Isolated state class for Fundamental Analysis subgraph.
Following LangGraph best practices - does NOT share node_statuses with parent.
"""

from typing import Annotated

from pydantic import BaseModel, Field

from ...state import (
    FundamentalAnalysisContext,
    IntentExtractionContext,
    last_value,
    merge_dict,
    merge_fundamental_context,
)


class FundamentalAnalysisSubgraphState(BaseModel):
    """
    Isolated state for fundamental analysis subgraph.

    This state is completely separate from the parent AgentState.
    It does NOT include node_statuses to prevent stale status updates.
    Uses Pydantic BaseModel to match parent AgentState structure.
    """

    # Input from parent
    ticker: str | None
    # TODO: Add model_type field here in the future to support explicit model selection in Fundamental Analysis
    intent_extraction: (
        IntentExtractionContext  # Needed for resolved_ticker and company_profile
    )
    fundamental: Annotated[FundamentalAnalysisContext, merge_fundamental_context]

    # Internal progress tracking (NOT shared with parent)
    internal_progress: Annotated[dict[str, str], merge_dict] = Field(
        default_factory=dict
    )

    # Current node tracking
    current_node: Annotated[str, last_value] = ""
