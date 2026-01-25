"""
Isolated state class for Technical Analysis subgraph.
Following LangGraph best practices - does NOT share node_statuses with parent.
"""

from typing import Annotated, Any

from langgraph.graph import add_messages
from pydantic import BaseModel, Field

from ...state import (
    IntentExtractionContext,
    TechnicalAnalysisContext,
    create_pydantic_reducer,
    last_value,
    merge_dict,
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
    messages: list = Field(default_factory=list)


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
        TechnicalAnalysisContext, create_pydantic_reducer(TechnicalAnalysisContext)
    ] = Field(default_factory=TechnicalAnalysisContext)
    messages: Annotated[list, add_messages] = Field(default_factory=list)

    # --- Intermediate State (Multi-stage pipeline) ---
    price_series: dict[str, float] = Field(
        default_factory=dict, description="Historical price data {date: price}"
    )
    volume_series: dict[str, float] = Field(
        default_factory=dict, description="Historical volume data {date: volume}"
    )
    fracdiff_series: dict[str, float] = Field(
        default_factory=dict, description="Fractionally differentiated price series"
    )
    z_score_series: dict[str, float] = Field(
        default_factory=dict, description="Rolling Z-score of fracdiff series"
    )
    fracdiff_metrics: dict[str, Any] = Field(
        default_factory=dict,
        description="FracDiff parameters: optimal_d, adf_statistic, etc.",
    )
    indicators: dict[str, Any] = Field(
        default_factory=dict,
        description="Technical indicators: bollinger, macd, obv, etc.",
    )

    # --- Private State ---
    internal_progress: Annotated[dict[str, str], merge_dict] = Field(
        default_factory=dict
    )
    current_node: Annotated[str, last_value] = ""
