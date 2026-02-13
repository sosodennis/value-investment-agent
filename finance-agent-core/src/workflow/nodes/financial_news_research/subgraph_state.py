"""
Isolated state class for Financial News Research subgraph.
Shared node_statuses with parent.
"""

from typing import Annotated, NotRequired

from langgraph.graph import add_messages
from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import TypedDict

from ...state import (
    FinancialNewsContext,
    IntentExtractionContext,
    append_logs,
    last_value,
    merge_dict,
)


class FinancialNewsInput(BaseModel):
    """
    Input schema for financial news research subgraph.
    Kept as Pydantic for boundary validation (Charter §3.1).
    """

    model_config = ConfigDict(extra="ignore")

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
    node_statuses: dict[str, str] = Field(default_factory=dict)
    error_logs: list[dict] = Field(default_factory=list)


class FinancialNewsState(TypedDict):
    """
    Internal state for financial news research subgraph.
    Converted to TypedDict per Engineering Charter v3.1 §3.1.

    Intermediate pipeline payloads are persisted via Artifact Store IDs only.
    No in-state mirror payloads are allowed.
    """

    # --- From Input ---
    ticker: NotRequired[str | None]
    intent_extraction: NotRequired[IntentExtractionContext]

    # --- Core State (Using TypedDict reducers) ---
    financial_news_research: Annotated[FinancialNewsContext, merge_dict]

    messages: Annotated[list, add_messages]

    # --- Intermediate State (Replaced by Artifact Store) ---
    # raw_results: Removed (Use search_artifact_id)
    # formatted_results: Removed (Use search_artifact_id)
    # selected_indices: Removed (Use selection_artifact_id)
    # news_items: Removed (Use news_items_artifact_id)

    # --- Private State (for node coordination) ---
    internal_progress: Annotated[dict[str, str], merge_dict]
    current_node: Annotated[str, last_value]
    node_statuses: Annotated[dict[str, str], merge_dict]
    error_logs: Annotated[list[dict], append_logs]
