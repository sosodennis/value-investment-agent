"""
Shared state definitions for the workflow graph.
"""

from typing import Annotated, Any, TypeVar

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages
from pydantic import BaseModel, Field

from src.interface.schemas import AgentOutputArtifact


def merge_dict(a: dict, b: dict) -> dict:
    """Simple dict merge reducer."""
    return {**a, **b}


def last_value(a: str | None, b: str | None) -> str | None:
    """Reducer that keeps the last non-None value. Used for parallel node updates."""
    return b if b is not None else a


# --- Generic Reducer ---

T = TypeVar("T", bound=BaseModel)


def create_pydantic_reducer(model_class: type[T]):
    """Factory function: Generates a standard Merge Reducer for any Pydantic Model."""

    def reducer(current: T | None, new: T | dict) -> T:
        if current is None:
            current = model_class()

        # Capture raw history if available from model instance
        # This prevents model_dump from stripping message metadata types (role/type)
        raw_history = None
        if isinstance(new, model_class) and hasattr(new, "history"):
            raw_history = new.history

        # Handle new data
        if isinstance(new, model_class):
            new_data = new.model_dump(exclude_unset=True)
        else:
            new_data = new

        # Special handling for 'history' field (common pattern in LangGraph)
        # Verify both current and new data have history to avoid errors

        # Use raw_history if available (preferred), otherwise fall back to new_data dict
        history_update = (
            raw_history if raw_history is not None else new_data.get("history")
        )

        if history_update is not None and hasattr(current, "history"):
            # Use LangGraph's add_messages to handle message appending/updates correctly
            current.history = add_messages(current.history, history_update)

        # Pydantic copy & update
        # Using model_copy with update is robust
        updated = current.model_copy(update=new_data)
        return updated

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
