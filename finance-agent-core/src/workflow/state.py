"""
Shared state definitions for the workflow graph.
"""

from typing import Annotated, Any

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages
from pydantic import BaseModel, Field

from .schemas import AuditOutput, CalculationOutput, ExtractionOutput


def merge_dict(a: dict, b: dict) -> dict:
    """Simple dict merge reducer."""
    return {**a, **b}


def last_value(a: str | None, b: str | None) -> str | None:
    """Reducer that keeps the last non-None value. Used for parallel node updates."""
    return b if b is not None else a


class AgentState(BaseModel):
    """Agent state defined as a Pydantic model."""

    user_query: str | None = None
    messages: Annotated[list[AnyMessage], add_messages] = Field(default_factory=list)
    ticker: str | None = None
    model_type: str | None = None

    # Refactored fields with strict schemas
    extraction_output: ExtractionOutput | None = Field(
        None, description="Output from Executor"
    )
    audit_output: AuditOutput | None = Field(None, description="Output from Auditor")
    calculation_output: CalculationOutput | None = Field(
        None, description="Output from Calculator"
    )

    # Fundamental Analysis metadata (kept as Dict/List for now, could be refactored later)
    fundamental_analysis_output: dict[str, Any] | None = None
    extracted_intent: dict[str, Any] | None = None
    ticker_candidates: list[Any] | None = None
    resolved_ticker: str | None = None
    company_profile: dict[str, Any] | None = None
    financial_reports: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Financial Health Reports from edgartools (Multi-year)",
    )
    financial_news_output: dict[str, Any] | None = Field(
        None, description="Output from Financial News Research"
    )
    selected_symbol: str | None = None
    approved: bool | None = None

    # Debate Agency fields
    debate_history: Annotated[list[AnyMessage], add_messages] = Field(
        default_factory=list, description="Adversarial conversation transcript"
    )
    bull_thesis: Annotated[str | None, last_value] = Field(
        None, description="The current strongest argument for LONG"
    )
    bear_thesis: Annotated[str | None, last_value] = Field(
        None, description="The current strongest argument for SHORT"
    )
    debate_conclusion: dict[str, Any] | None = Field(
        None, description="Final structure output: DebateConclusion"
    )
    debate_current_round: int = 0
    analyst_reports: dict[str, Any] | None = Field(
        None, description="Aggregated ground truth (news + financials) for debate"
    )

    # Dashboard tracking
    node_statuses: Annotated[dict[str, str], merge_dict] = Field(
        default_factory=dict,
        description="Status of each node: idle, running, done, error",
    )
    current_node: Annotated[str | None, last_value] = None
