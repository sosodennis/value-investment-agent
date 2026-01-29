"""
Isolated state class for Financial News Research subgraph.
Following LangGraph best practices - does NOT share node_statuses with parent.
"""

from typing import Annotated, NotRequired, TypedDict

from langgraph.graph import add_messages
from pydantic import BaseModel, Field

from ...state import (
    FinancialNewsContext,
    IntentExtractionContext,
    last_value,
    merge_dict,
)


class FinancialNewsInput(BaseModel):
    """
    Input schema for financial news research subgraph.
    Kept as Pydantic for boundary validation (Charter §3.1).
    """

    ticker: str | None = None
    intent_extraction: IntentExtractionContext = Field(default_factory=dict)
    financial_news_research: FinancialNewsContext = Field(default_factory=dict)


class FinancialNewsOutput(BaseModel):
    """
    Output schema for financial news research subgraph.
    Kept as Pydantic for boundary validation (Charter §3.1).
    """

    financial_news_research: FinancialNewsContext
    messages: list = Field(default_factory=list)


class FinancialNewsState(TypedDict):
    """
    Internal state for financial news research subgraph.
    Converted to TypedDict per Engineering Charter v3.1 §3.1.

    NOTE: Intermediate pipeline data (raw_results, formatted_results, etc.)
    is temporarily kept for backward compatibility with existing graph nodes.
    These will be removed when graph nodes are refactored to use Artifact Store.
    """

    # --- From Input ---
    ticker: NotRequired[str | None]
    intent_extraction: NotRequired[IntentExtractionContext]

    # --- Core State (Using TypedDict reducers) ---
    financial_news_research: Annotated[FinancialNewsContext, merge_dict]

    messages: Annotated[list, add_messages]

    # --- Intermediate State (TODO: Remove when graph uses Artifact Store) ---
    raw_results: NotRequired[list[dict]]
    formatted_results: NotRequired[str]
    selected_indices: NotRequired[list[int]]
    news_items: NotRequired[list[dict]]

    # --- Private State (for node coordination) ---
    internal_progress: Annotated[dict[str, str], merge_dict]
    current_node: Annotated[str, last_value]
