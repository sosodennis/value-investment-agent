"""
Shared state definitions for the workflow graph.
"""

from typing import List, Dict, Optional, Any, Annotated
from pydantic import BaseModel, Field
from langgraph.graph import add_messages
from langchain_core.messages import AnyMessage

from .schemas import ExtractionOutput, AuditOutput, CalculationOutput

class AgentState(BaseModel):
    """Agent state defined as a Pydantic model."""
    user_query: Optional[str] = None
    messages: Annotated[List[AnyMessage], add_messages] = Field(default_factory=list)
    ticker: Optional[str] = None
    model_type: Optional[str] = None
    
    # Refactored fields with strict schemas
    extraction_output: Optional[ExtractionOutput] = Field(None, description="Output from Executor")
    audit_output: Optional[AuditOutput] = Field(None, description="Output from Auditor")
    calculation_output: Optional[CalculationOutput] = Field(None, description="Output from Calculator")
    
    # Planner metadata (kept as Dict/List for now, could be refactored later)
    planner_output: Optional[Dict[str, Any]] = None
    extracted_intent: Optional[Dict[str, Any]] = None
    ticker_candidates: Optional[List[Any]] = None
    resolved_ticker: Optional[str] = None
    company_profile: Optional[Dict[str, Any]] = None
    status: Optional[str] = None
    selected_symbol: Optional[str] = None
    approved: Optional[bool] = None

