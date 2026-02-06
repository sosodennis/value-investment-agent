from typing import Annotated

from langgraph.graph import add_messages
from typing_extensions import NotRequired, TypedDict

from ...state import (
    FundamentalAnalysisContext,
    IntentExtractionContext,
    append_logs,
    last_value,
    merge_dict,
)


class AuditorInput(TypedDict):
    fundamental_analysis: FundamentalAnalysisContext
    intent_extraction: NotRequired[IntentExtractionContext]


class AuditorOutput(TypedDict):
    fundamental_analysis: FundamentalAnalysisContext
    node_statuses: dict[str, str]
    error_logs: list[dict]


class AuditorState(TypedDict):
    ticker: NotRequired[str]
    intent_extraction: NotRequired[IntentExtractionContext]
    fundamental_analysis: Annotated[FundamentalAnalysisContext, merge_dict]
    messages: Annotated[list, add_messages]
    error_logs: Annotated[list[dict], append_logs]
    internal_progress: Annotated[dict[str, str], merge_dict]
    current_node: Annotated[str, last_value]
    node_statuses: Annotated[dict[str, str], merge_dict]
