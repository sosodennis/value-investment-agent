from src.agents.intent.application.intent_service import _heuristic_extract
from src.agents.intent.interface.contracts import IntentExtraction


def test_heuristic_extract_nvidia_valuation():
    query = "NVIDIA Valuation"
    result = _heuristic_extract(query, intent_model_factory=IntentExtraction)
    assert result.company_name == "NVIDIA"
    assert result.ticker is None  # Expected behavior if no ticker symbol is present


def test_heuristic_extract_valuate_tesla():
    query = "Valuate Tesla"
    result = _heuristic_extract(query, intent_model_factory=IntentExtraction)
    assert result.company_name == "Tesla"


def test_heuristic_extract_google_stock_price():
    query = "Google stock price"
    result = _heuristic_extract(query, intent_model_factory=IntentExtraction)
    assert result.company_name == "Google"


def test_heuristic_extract_simple_ticker():
    query = "AAPL"
    result = _heuristic_extract(query, intent_model_factory=IntentExtraction)
    assert result.ticker == "AAPL"
    assert result.company_name == "AAPL"


def test_heuristic_extract_ticker_valuation():
    query = "MSFT Valuation"
    result = _heuristic_extract(query, intent_model_factory=IntentExtraction)
    assert result.ticker == "MSFT"
    assert result.company_name == "MSFT"
