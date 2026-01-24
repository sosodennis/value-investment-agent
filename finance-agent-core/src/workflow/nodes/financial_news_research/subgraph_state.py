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

    financial_news: FinancialNewsContext


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
    financial_news: Annotated[FinancialNewsContext, merge_financial_news_context] = (
        Field(default_factory=FinancialNewsContext)
    )

    # --- Private State ---
    internal_progress: Annotated[dict[str, str], merge_dict] = Field(
        default_factory=dict
    )
    current_node: Annotated[str, last_value] = ""
