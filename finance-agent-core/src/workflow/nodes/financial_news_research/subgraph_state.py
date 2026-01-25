"""
Isolated state class for Financial News Research subgraph.
Following LangGraph best practices - does NOT share node_statuses with parent.
"""

from typing import Annotated

from langgraph.graph import add_messages
from pydantic import BaseModel, Field

from src.interface.schemas import AgentOutputArtifact

from ...state import (
    FinancialNewsContext,
    IntentExtractionContext,
    last_value,
    merge_dict,
    merge_financial_news_context,
)


class FinancialNewsInput(BaseModel):
    """
    Input schema for financial news research subgraph.
    """

    ticker: str | None = None
    intent_extraction: IntentExtractionContext = Field(
        default_factory=IntentExtractionContext
    )
    financial_news: FinancialNewsContext = Field(default_factory=FinancialNewsContext)


class FinancialNewsOutput(BaseModel):
    """
    Output schema for financial news research subgraph.
    """

    financial_news_research: FinancialNewsContext
    artifact: AgentOutputArtifact | None = None
    messages: list = Field(default_factory=list)


class FinancialNewsState(BaseModel):
    """
    Internal state for financial news research subgraph.
    """

    # --- From Input ---
    ticker: str | None = None
    intent_extraction: IntentExtractionContext = Field(
        default_factory=IntentExtractionContext
    )

    # --- Core State (Reducers applied) ---
    financial_news_research: Annotated[
        FinancialNewsContext, merge_financial_news_context
    ] = Field(default_factory=FinancialNewsContext)

    # --- Output (Direct in State layer for Flat Pattern) ---
    artifact: AgentOutputArtifact | None = None
    messages: Annotated[list, add_messages] = Field(default_factory=list)

    # --- Intermediate State (Multi-stage pipeline) ---
    raw_results: list[dict] = Field(
        default_factory=list, description="Raw search results from news API"
    )
    formatted_results: str = Field(
        default="", description="Formatted search results for LLM selection"
    )
    selected_indices: list[int] = Field(
        default_factory=list,
        description="Indices of articles selected by LLM for deep analysis",
    )
    news_items: list[dict] = Field(
        default_factory=list,
        description="Fetched articles with full content and analysis",
    )

    # --- Private State ---
    internal_progress: Annotated[dict[str, str], merge_dict] = Field(
        default_factory=dict
    )
    current_node: Annotated[str, last_value] = ""
