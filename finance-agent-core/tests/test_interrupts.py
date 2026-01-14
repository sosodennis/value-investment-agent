import pytest
from pydantic import TypeAdapter, ValidationError

from src.workflow.interrupts import (
    ApprovalDetails,
    HumanApprovalRequest,
    HumanTickerSelection,
    InterruptValue,
)
from src.workflow.nodes.fundamental_analysis.extraction import IntentExtraction
from src.workflow.nodes.fundamental_analysis.structures import TickerCandidate


def test_approval_request_serialization():
    details = ApprovalDetails(
        ticker="TSLA",
        model="saas",
        audit_passed=True,
        audit_messages=["Check 1 passed"],
    )
    request = HumanApprovalRequest(details=details)

    dump = request.model_dump()
    assert dump["type"] == "approval_request"
    assert dump["details"]["ticker"] == "TSLA"
    assert dump["details"]["audit_passed"] is True


def test_ticker_selection_serialization():
    candidates = [TickerCandidate(symbol="AAPL", name="Apple Inc.", confidence=0.9)]
    intent = IntentExtraction(
        company_name="Apple",
        is_valuation_request=True,
        reasoning="User asked for Apple",
    )
    selection = HumanTickerSelection(
        candidates=candidates, intent=intent, reason="Ambiguous"
    )

    dump = selection.model_dump()
    assert dump["type"] == "ticker_selection"
    assert len(dump["candidates"]) == 1
    assert dump["candidates"][0]["symbol"] == "AAPL"
    assert dump["intent"]["company_name"] == "Apple"


def test_interrupt_value_validation():
    adapter = TypeAdapter(InterruptValue)
    # Valid approval request
    data = {
        "type": "approval_request",
        "action": "calculate_valuation",
        "details": {"ticker": "MSFT", "model": "bank", "audit_passed": False},
    }
    val = adapter.validate_python(data)
    assert isinstance(val, HumanApprovalRequest)

    # Valid ticker selection
    data = {
        "type": "ticker_selection",
        "candidates": [{"symbol": "GOOG", "name": "Google", "confidence": 1.0}],
        "reason": "Test",
    }
    val = adapter.validate_python(data)
    assert isinstance(val, HumanTickerSelection)


def test_invalid_interrupt_validation():
    adapter = TypeAdapter(InterruptValue)
    with pytest.raises(ValidationError):
        adapter.validate_python({"type": "unknown"})
