"""
Shared state definitions for the workflow graph.
"""

from typing import Annotated, Any, TypeVar

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages
from pydantic import BaseModel, Field

from src.interface.schemas import AgentOutputArtifact

from .schemas import AuditOutput, CalculationOutput, ExtractionOutput


def merge_dict(a: dict, b: dict) -> dict:
    """Simple dict merge reducer."""
    return {**a, **b}


def last_value(a: str | None, b: str | None) -> str | None:
    """Reducer that keeps the last non-None value. Used for parallel node updates."""
    return b if b is not None else a


# --- Generic Reducer ---

T = TypeVar("T", bound=BaseModel)


def create_pydantic_reducer(model_class: type[T]):
    """
    Factory function: Generates a standard Merge Reducer for any Pydantic Model.
    FIXED: Uses model_validate to ensure dicts are parsed into Pydantic models.
    """

    def reducer(current: T | None, new: T | dict) -> T:
        if current is None:
            current = model_class()

        # 1. Prepare new data (handle both objects and dicts)
        if isinstance(new, model_class):
            new_data = new.model_dump(exclude_unset=True)
        else:
            new_data = new

        # 2. Handle History merging (LangGraph special logic)
        raw_history_update = (
            getattr(new, "history", None)
            if isinstance(new, model_class)
            else new_data.get("history")
        )

        if raw_history_update is not None and hasattr(current, "history"):
            from langgraph.graph import add_messages

            # Use LangGraph's add_messages to handle message appending correctly
            merged_history = add_messages(current.history, raw_history_update)
            new_data["history"] = merged_history

        # 3. Execution of safe merge and validation (Critical Fix)
        # Using model_validate instead of model_copy(update=...) forces Pydantic
        # to parse nested dicts into proper Pydantic instances (e.g. AgentOutputArtifact).
        merged_data = current.model_dump()
        merged_data.update(new_data)

        return model_class.model_validate(merged_data)

    return reducer


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
    artifact: AgentOutputArtifact | None = Field(
        None, description="Standardized output artifact for UI"
    )


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
    current_round: int = 0
    analyst_reports: dict[str, Any] | None = Field(
        None, description="Aggregated ground truth (news + financials) for debate"
    )
    artifact: AgentOutputArtifact | None = Field(
        None, description="Standardized output artifact for UI"
    )


class FundamentalAnalysisContext(BaseModel):
    financial_reports: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Financial Health Reports from edgartools (Multi-year)",
    )
    approved: bool | None = None
    status: str | None = None
    model_type: str | None = Field(
        None, description="The skill/model to use for valuation (e.g. saas, bank)"
    )
    # TODO: Refactor executor, auditor, and calculator into their own sub-agent with dedicated context
    # These fields should move to a new ExecutorContext/AuditorContext in the future
    extraction_output: ExtractionOutput | None = Field(
        None, description="Extracted parameters from executor node"
    )
    audit_output: AuditOutput | None = Field(
        None, description="Audit results from auditor node"
    )
    calculation_output: CalculationOutput | None = Field(
        None, description="Final results from calculator node"
    )
    artifact: AgentOutputArtifact | None = None


class FinancialNewsContext(BaseModel):
    artifact: AgentOutputArtifact | None = None


class TechnicalAnalysisContext(BaseModel):
    artifact: AgentOutputArtifact | None = None


class AgentState(BaseModel):
    """Agent state defined as a Pydantic model."""

    user_query: Annotated[str | None, last_value] = None
    messages: Annotated[list[AnyMessage], add_messages] = Field(default_factory=list)
    ticker: Annotated[str | None, last_value] = None

    # Sub-Agent Contexts
    intent_extraction: Annotated[
        IntentExtractionContext, create_pydantic_reducer(IntentExtractionContext)
    ] = Field(default_factory=IntentExtractionContext)

    fundamental_analysis: Annotated[
        FundamentalAnalysisContext, create_pydantic_reducer(FundamentalAnalysisContext)
    ] = Field(default_factory=FundamentalAnalysisContext)

    financial_news_research: Annotated[
        FinancialNewsContext, create_pydantic_reducer(FinancialNewsContext)
    ] = Field(default_factory=FinancialNewsContext)

    technical_analysis: Annotated[
        TechnicalAnalysisContext, create_pydantic_reducer(TechnicalAnalysisContext)
    ] = Field(default_factory=TechnicalAnalysisContext)

    debate: Annotated[DebateContext, create_pydantic_reducer(DebateContext)] = Field(
        default_factory=DebateContext
    )

    # Dashboard tracking
    node_statuses: Annotated[dict[str, str], merge_dict] = Field(
        default_factory=dict,
        description="Status of each node: idle, running, done, error",
    )

    current_node: Annotated[str | None, last_value] = None
