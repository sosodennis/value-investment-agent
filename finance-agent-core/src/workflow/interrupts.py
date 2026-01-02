from typing import Literal

from langchain_core.messages import AIMessage  # noqa: F401
from pydantic import BaseModel, Field

from .nodes.planner.extraction import IntentExtraction
from .nodes.planner.structures import TickerCandidate


class ApprovalDetails(BaseModel):
    """Details for human approval of a valuation."""

    ticker: str | None = None
    model: str | None = None
    audit_passed: bool = False
    audit_messages: list[str] = Field(default_factory=list)


class HumanApprovalRequest(BaseModel):
    """Payload for human approval interrupt."""

    type: Literal["approval_request"] = "approval_request"
    action: str = "calculate_valuation"
    details: ApprovalDetails


class HumanTickerSelection(BaseModel):
    """Payload for ticker selection interrupt."""

    type: Literal["ticker_selection"] = "ticker_selection"
    candidates: list[TickerCandidate] = Field(default_factory=list)
    intent: IntentExtraction | None = None
    reason: str = "Multiple tickers found or ambiguity detected."


# Composite type for all possible interrupts
InterruptValue = HumanApprovalRequest | HumanTickerSelection
