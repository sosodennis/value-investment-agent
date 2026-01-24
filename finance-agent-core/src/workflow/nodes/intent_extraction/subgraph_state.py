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


class IntentExtractionInput(BaseModel):
    """
    Input schema for Intent Extraction subgraph.
    """

    ticker: str | None = None
    user_query: str | None = None
    messages: list = Field(default_factory=list)
    intent_extraction: IntentExtractionContext = Field(
        default_factory=IntentExtractionContext
    )


class IntentExtractionOutput(BaseModel):
    """
    Output schema for Intent Extraction subgraph.
    """

    intent_extraction: IntentExtractionContext
    ticker: str | None = None


class IntentExtractionState(BaseModel):
    """
    Internal state for intent extraction subgraph.
    """

    # --- From Input ---
    ticker: str | None = None
    user_query: str | None = None
    messages: list = Field(default_factory=list)

    # --- Core State (Reducers applied) ---
    intent_extraction: Annotated[
        IntentExtractionContext, merge_intent_extraction_context
    ] = Field(default_factory=IntentExtractionContext)

    # --- Private State ---
    internal_progress: Annotated[dict[str, str], merge_dict] = Field(
        default_factory=dict
    )
    current_node: Annotated[str, last_value] = ""
