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


class FundamentalAnalysisInput(BaseModel):
    """
    Input schema for Fundamental Analysis subgraph.
    Defines the contract for what the parent graph must provide.
    """

    ticker: str | None = None
    intent_extraction: IntentExtractionContext = Field(
        default_factory=IntentExtractionContext
    )


class FundamentalAnalysisOutput(BaseModel):
    """
    Output schema for Fundamental Analysis subgraph.
    Defines exactly what fields are returned to the parent state.
    """

    fundamental: FundamentalAnalysisContext


class FundamentalAnalysisState(BaseModel):
    """
    Internal state for fundamental analysis subgraph.
    Combines input fields, output fields, and private state.
    """

    # --- From Input ---
    ticker: str | None = None
    intent_extraction: IntentExtractionContext = Field(
        default_factory=IntentExtractionContext
    )

    # --- Core State (Reducers applied) ---
    fundamental: Annotated[FundamentalAnalysisContext, merge_fundamental_context] = (
        Field(default_factory=FundamentalAnalysisContext)
    )

    # --- Private State (Not exposed in FundamentalAnalysisOutput) ---
    internal_progress: Annotated[dict[str, str], merge_dict] = Field(
        default_factory=dict
    )
    current_node: Annotated[str, last_value] = ""
    model_type: Annotated[str, last_value] = "saas"
