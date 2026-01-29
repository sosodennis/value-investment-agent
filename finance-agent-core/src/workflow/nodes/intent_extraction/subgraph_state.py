from typing import Annotated, TypedDict

from langgraph.graph import add_messages
from pydantic import BaseModel, Field

from ...state import IntentExtractionContext, merge_dict


class IntentExtractionInput(BaseModel):
    """
    Input schema for Intent Extraction subgraph.
    Boundary validation remains Pydantic.
    """

    ticker: str | None = None
    user_query: str | None = None
    messages: list = Field(default_factory=list)
    intent_extraction: IntentExtractionContext = Field(default_factory=dict)


class IntentExtractionOutput(BaseModel):
    """
    Output schema for Intent Extraction subgraph.
    Boundary validation remains Pydantic.
    """

    intent_extraction: IntentExtractionContext
    ticker: str | None = None
    messages: list = Field(default_factory=list)


class IntentExtractionState(TypedDict):
    """
    Internal state for intent extraction subgraph.
    Uses TypedDict for performance and LangGraph native compatibility.
    """

    # --- From Input ---
    ticker: str | None
    user_query: str | None

    # --- Core State (Reducers applied) ---
    # Note: Using default overwrite for intent_extraction context.
    # Individual fields within the context are managed by nodes.
    intent_extraction: IntentExtractionContext
    messages: Annotated[list, add_messages]

    # --- Private State ---
    internal_progress: Annotated[dict[str, str], merge_dict]
    current_node: str
