"""
Isolated state class for Intent Extraction subgraph.
Following LangGraph best practices - does NOT share node_statuses with parent.
"""

from typing import Annotated

from pydantic import BaseModel, Field

from ...state import (
    IntentExtractionContext,
    last_value,
    merge_dict,
    merge_intent_extraction_context,
)


class IntentExtractionSubgraphState(BaseModel):
    """
    Isolated state for intent extraction subgraph.

    This state is completely separate from the parent AgentState.
    It does NOT include node_statuses to prevent stale status updates.
    Uses Pydantic BaseModel to match parent AgentState structure.
    """

    # Input from parent (ticker is None initially)
    ticker: str | None
    user_query: str | None  # Needed by intent extraction nodes
    messages: list
    intent_extraction: Annotated[
        IntentExtractionContext, merge_intent_extraction_context
    ]

    # Internal progress tracking (NOT shared with parent)
    internal_progress: Annotated[dict[str, str], merge_dict] = Field(
        default_factory=dict
    )

    # Current node tracking
    current_node: Annotated[str, last_value] = ""
