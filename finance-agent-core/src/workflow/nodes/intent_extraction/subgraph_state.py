"""
Isolated state class for Intent Extraction subgraph.
Following LangGraph best practices - does NOT share node_statuses with parent.
"""

from typing import Annotated

from langgraph.graph import add_messages
from pydantic import BaseModel, Field

from ...state import (
    IntentExtractionContext,
    create_pydantic_reducer,
    last_value,
    merge_dict,
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
    messages: list = Field(default_factory=list)


class IntentExtractionState(BaseModel):
    """
    Internal state for intent extraction subgraph.
    """

    # --- From Input ---
    ticker: str | None = None
    user_query: str | None = None

    # --- Core State (Reducers applied) ---
    intent_extraction: Annotated[
        IntentExtractionContext, create_pydantic_reducer(IntentExtractionContext)
    ] = Field(default_factory=IntentExtractionContext)
    messages: Annotated[list, add_messages] = Field(default_factory=list)

    # --- Private State ---
    internal_progress: Annotated[dict[str, str], merge_dict] = Field(
        default_factory=dict
    )
    current_node: Annotated[str, last_value] = ""
