from typing import List, Dict, Optional, Union, Any, Literal
from pydantic import BaseModel, Field
from .nodes.planner.structures import TickerCandidate

class ApprovalDetails(BaseModel):
    """Details for human approval of a valuation."""
    ticker: Optional[str] = None
    model: Optional[str] = None
    audit_passed: bool = False
    audit_messages: List[str] = Field(default_factory=list)

class HumanApprovalRequest(BaseModel):
    """Payload for human approval interrupt."""
    type: Literal["approval_request"] = "approval_request"
    action: str = "calculate_valuation"
    details: ApprovalDetails

from .nodes.planner.extraction import IntentExtraction

class HumanTickerSelection(BaseModel):
    """Payload for ticker selection interrupt."""
    type: Literal["ticker_selection"] = "ticker_selection"
    candidates: List[TickerCandidate] = Field(default_factory=list)
    intent: Optional[IntentExtraction] = None
    reason: str = "Multiple tickers found or ambiguity detected."

# Composite type for all possible interrupts
InterruptValue = Union[HumanApprovalRequest, HumanTickerSelection]
