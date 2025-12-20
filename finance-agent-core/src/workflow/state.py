"""
Shared state definitions for the workflow graph.
"""

from typing import Any, Dict, Optional
from typing_extensions import TypedDict
from langgraph.graph import add_messages
from langchain_core.messages import AnyMessage


class AgentState(TypedDict, total=False):
    """Agent state with all fields optional for LangServe compatibility."""
    user_query: str
    messages: list[AnyMessage]  # For conversation history
    ticker: str
    model_type: str  # 'saas' or 'bank'
    params: Dict[str, Any]  # Serialized JSON of params
    audit_report: Dict[str, Any]  # {passed: bool, messages: []}
    valuation_result: Dict[str, Any]
    planner_output: Dict[str, Any]  # Metadata from planner (sector, industry, reasoning)
    # Planner subgraph fields
    extracted_intent: Dict[str, Any]
    ticker_candidates: list
    resolved_ticker: str
    company_profile: Dict[str, Any]
    status: str  # Planner status: 'extracting', 'searching', 'clarifying', 'done'
    selected_symbol: str  # For HITL selection
    approved: bool  # For human approval before calculation

