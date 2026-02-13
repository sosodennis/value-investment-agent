import pytest
from pydantic import TypeAdapter, ValidationError

from src.agents.intent.interface.contracts import IntentExtraction, TickerCandidateModel
from src.workflow.interrupts import HumanTickerSelection, InterruptValue


def test_ticker_selection_serialization():
    candidates = [
        TickerCandidateModel(symbol="AAPL", name="Apple Inc.", confidence=0.9)
    ]
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


def test_ticker_selection_ui_payload_uses_one_of():
    candidates = [
        TickerCandidateModel(symbol="AAPL", name="Apple Inc.", confidence=0.9),
        TickerCandidateModel(symbol="AAPL34", name="Apple Brasil", confidence=0.7),
    ]
    selection = HumanTickerSelection(candidates=candidates)

    payload = selection.to_ui_payload()
    schema = payload["schema"]
    selected_symbol = schema["properties"]["selected_symbol"]

    assert selected_symbol["enum"] == ["AAPL", "AAPL34"]
    assert "enumNames" not in selected_symbol
    assert selected_symbol["oneOf"][0]["const"] == "AAPL"
    assert selected_symbol["oneOf"][0]["title"].startswith("AAPL - Apple Inc.")


def test_interrupt_value_validation():
    adapter = TypeAdapter(InterruptValue)
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
