"""
Isolated state class for Technical Analysis subgraph.
Following LangGraph best practices - does NOT share node_statuses with parent.
"""

from typing import Annotated

from pydantic import BaseModel, Field

from ...state import (
    IntentExtractionContext,
    TechnicalAnalysisContext,
    last_value,
    merge_dict,
    merge_technical_analysis_context,
)


class TechnicalAnalysisSubgraphState(BaseModel):
    """
    Isolated state for technical analysis subgraph.

    This state is completely separate from the parent AgentState.
    It does NOT include node_statuses to prevent stale status updates.
    Uses Pydantic BaseModel to match parent AgentState structure.
    """

    # Input from parent
    ticker: str | None
    intent_extraction: IntentExtractionContext  # Needed for resolved_ticker
    technical_analysis: Annotated[
        TechnicalAnalysisContext, merge_technical_analysis_context
    ]

    # Internal progress tracking (NOT shared with parent)
    internal_progress: Annotated[dict[str, str], merge_dict] = Field(
        default_factory=dict
    )

    # Current node tracking
    current_node: Annotated[str, last_value] = ""
