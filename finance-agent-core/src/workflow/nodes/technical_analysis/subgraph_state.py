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


class TechnicalAnalysisInput(BaseModel):
    """
    Input schema for technical analysis subgraph.
    """

    ticker: str | None = None
    intent_extraction: IntentExtractionContext = Field(
        default_factory=IntentExtractionContext
    )
    technical_analysis: TechnicalAnalysisContext = Field(
        default_factory=TechnicalAnalysisContext
    )


class TechnicalAnalysisOutput(BaseModel):
    """
    Output schema for technical analysis subgraph.
    """

    technical_analysis: TechnicalAnalysisContext


class TechnicalAnalysisState(BaseModel):
    """
    Internal state for technical analysis subgraph.
    """

    # --- From Input ---
    ticker: str | None = None
    intent_extraction: IntentExtractionContext = Field(
        default_factory=IntentExtractionContext
    )

    # --- Core State (Reducers applied) ---
    technical_analysis: Annotated[
        TechnicalAnalysisContext, merge_technical_analysis_context
    ] = Field(default_factory=TechnicalAnalysisContext)

    # --- Private State ---
    internal_progress: Annotated[dict[str, str], merge_dict] = Field(
        default_factory=dict
    )
    current_node: Annotated[str, last_value] = ""
