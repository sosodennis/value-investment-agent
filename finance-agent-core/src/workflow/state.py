"""
Shared state definitions for the workflow graph.
"""

from typing import Any, Dict, Optional, TypedDict


class AgentState(TypedDict):
    user_query: Optional[str]
    messages: Optional[list]  # For conversation history
    ticker: Optional[str]
    model_type: Optional[str]  # 'saas' or 'bank'
    params: Optional[Dict[str, Any]]  # Serialized JSON of params
    audit_report: Optional[Dict[str, Any]]  # {passed: bool, messages: []}
    valuation_result: Optional[Dict[str, Any]]
    planner_output: Optional[Dict[str, Any]]  # Metadata from planner (sector, industry, reasoning)
    # Planner subgraph fields
    extracted_intent: Optional[Dict[str, Any]]
    ticker_candidates: Optional[list]
    resolved_ticker: Optional[str]
    company_profile: Optional[Dict[str, Any]]
    status: Optional[str]  # Planner status: 'extracting', 'searching', 'clarifying', 'done'
    selected_symbol: Optional[str] # For HITL selection
