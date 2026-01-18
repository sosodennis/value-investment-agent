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


# --- Context Models ---


class IntentExtractionContext(BaseModel):
    """Context for intent extraction workflow."""

    extracted_intent: dict[str, Any] | None = Field(
        None, description="Parsed intent from user query (ticker, company_name, etc.)"
    )
    ticker_candidates: list[Any] | None = Field(
        None, description="List of possible ticker matches from search"
    )
    resolved_ticker: str | None = Field(
        None, description="Final resolved ticker symbol"
    )
    company_profile: dict[str, Any] | None = Field(
        None, description="Company profile information for resolved ticker"
    )
    status: str | None = Field(
        None,
        description="Current status: extraction, searching, deciding, clarifying, resolved",
    )


def merge_intent_extraction_context(
    current: IntentExtractionContext | None, new: IntentExtractionContext | dict
) -> IntentExtractionContext:
    """Merge function for IntentExtractionContext."""
    if current is None:
        current = IntentExtractionContext()

    if isinstance(new, IntentExtractionContext):
        new_data = new.model_dump()
    else:
        new_data = new

    for k, v in new_data.items():
        if v is not None:
            setattr(current, k, v)

    return current


class DebateContext(BaseModel):
    history: list[AnyMessage] = Field(
        default_factory=list, description="Adversarial conversation transcript"
    )
    bull_thesis: str | None = Field(
        None, description="The current strongest argument for LONG"
    )
    bear_thesis: str | None = Field(
        None, description="The current strongest argument for SHORT"
    )
    conclusion: dict[str, Any] | None = Field(
        None, description="Final structure output: DebateConclusion"
    )
    current_round: int = 0
    analyst_reports: dict[str, Any] | None = Field(
        None, description="Aggregated ground truth (news + financials) for debate"
    )


def merge_debate_context(
    current: DebateContext | None, new: DebateContext | dict
) -> DebateContext:
    if current is None:
        current = DebateContext()

    if isinstance(new, DebateContext):
        new_data = new.model_dump()
    else:
        new_data = new

    # Handle history merging with add_messages
    if "history" in new_data and new_data["history"] is not None:
        current.history = add_messages(current.history, new_data["history"])

    # Handle other fields
    for k, v in new_data.items():
        if k == "history":
            continue
        if v is not None:
            setattr(current, k, v)

    return current


class FundamentalAnalysisContext(BaseModel):
    analysis_output: dict[str, Any] | None = None
    financial_reports: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Financial Health Reports from edgartools (Multi-year)",
    )
    approved: bool | None = None
    status: str | None = None


def merge_fundamental_context(
    current: FundamentalAnalysisContext | None, new: FundamentalAnalysisContext | dict
) -> FundamentalAnalysisContext:
    if current is None:
        current = FundamentalAnalysisContext()

    if isinstance(new, FundamentalAnalysisContext):
        new_data = new.model_dump()
    else:
        new_data = new

    for k, v in new_data.items():
        if v is not None:
            setattr(current, k, v)

    return current


class FinancialNewsContext(BaseModel):
    output: dict[str, Any] | None = Field(
        None, description="Output from Financial News Research"
    )


def merge_financial_news_context(
    current: FinancialNewsContext | None, new: FinancialNewsContext | dict
) -> FinancialNewsContext:
    if current is None:
        current = FinancialNewsContext()

    if isinstance(new, FinancialNewsContext):
        new_data = new.model_dump()
    else:
        new_data = new

    for k, v in new_data.items():
        if v is not None:
            setattr(current, k, v)

    return current


class AgentState(BaseModel):
    """Agent state defined as a Pydantic model."""

    user_query: Annotated[str | None, last_value] = None
    messages: Annotated[list[AnyMessage], add_messages] = Field(default_factory=list)
    ticker: Annotated[str | None, last_value] = None
    model_type: Annotated[str | None, last_value] = None

    # Refactored fields with strict schemas
    extraction_output: Annotated[ExtractionOutput | None, last_value] = Field(
        None, description="Output from Executor"
    )
    audit_output: Annotated[AuditOutput | None, last_value] = Field(
        None, description="Output from Auditor"
    )
    calculation_output: Annotated[CalculationOutput | None, last_value] = Field(
        None, description="Output from Calculator"
    )

    # Sub-Agent Contexts
    intent_extraction: Annotated[
        IntentExtractionContext, merge_intent_extraction_context
    ] = Field(default_factory=IntentExtractionContext)
    fundamental: Annotated[FundamentalAnalysisContext, merge_fundamental_context] = (
        Field(default_factory=FundamentalAnalysisContext)
    )
    financial_news: Annotated[FinancialNewsContext, merge_financial_news_context] = (
        Field(default_factory=FinancialNewsContext)
    )
    debate: Annotated[DebateContext, merge_debate_context] = Field(
        default_factory=DebateContext
    )

    # Dashboard tracking
    node_statuses: Annotated[dict[str, str], merge_dict] = Field(
        default_factory=dict,
        description="Status of each node: idle, running, done, error",
    )
    current_node: Annotated[str | None, last_value] = None
