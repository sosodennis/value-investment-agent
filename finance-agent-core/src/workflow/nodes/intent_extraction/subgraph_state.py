from typing import Annotated

from langgraph.graph import add_messages
from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import TypedDict

from ...state import IntentExtractionContext, append_logs, last_value, merge_dict


class IntentExtractionInput(BaseModel):
    """
    Input schema for Intent Extraction subgraph.
    Boundary validation remains Pydantic.
    """

    model_config = ConfigDict(extra="ignore")

    ticker: str | None = None
    user_query: str | None = None
    messages: list = Field(default_factory=list)
    intent_extraction: IntentExtractionContext = Field(default_factory=dict)


class IntentExtractionOutput(BaseModel):
    """
    Output schema for Intent Extraction subgraph.
    Boundary validation remains Pydantic.
    """

    intent_extraction: IntentExtractionContext
    ticker: str | None = None
    messages: list = Field(default_factory=list)
    node_statuses: dict[str, str] = Field(default_factory=dict)
    error_logs: list[dict] = Field(default_factory=list)


class IntentExtractionState(TypedDict):
    """
    Internal state for intent extraction subgraph.
    Uses TypedDict for performance and native LangGraph state reducers.
    """

    # --- From Input ---
    ticker: str | None
    user_query: str | None

    # Core State (Reducers applied)
    # Using merge_dict to prevent overwriting of context during partial updates
    intent_extraction: Annotated[IntentExtractionContext, merge_dict]
    messages: Annotated[list, add_messages]

    # --- Private State ---
    internal_progress: Annotated[dict[str, str], merge_dict]
    current_node: Annotated[str, last_value]
    node_statuses: Annotated[dict[str, str], merge_dict]
    error_logs: Annotated[list[dict], append_logs]
