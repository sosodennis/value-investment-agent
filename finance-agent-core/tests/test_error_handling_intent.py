from unittest.mock import patch

import pytest

from src.agents.intent.domain.models import TickerCandidate
from src.workflow.nodes.intent_extraction.nodes import (
    decision_node,
    extraction_node,
    searching_node,
)


@pytest.mark.asyncio
async def test_extraction_node_error_degraded_path():
    state = {"user_query": "Analyze Apple"}

    with patch(
        "src.workflow.nodes.intent_extraction.nodes.intent_orchestrator.extract_intent",
        side_effect=Exception("LLM Error"),
    ):
        command = extraction_node(state)

        assert command.goto == "clarifying"
        assert command.update["node_statuses"]["intent_extraction"] == "degraded"
        assert (
            "Model failed to extract intent" in command.update["error_logs"][0]["error"]
        )


@pytest.mark.asyncio
async def test_searching_node_error_degraded_path():
    state = {
        "intent_extraction": {
            "extracted_intent": {"company_name": "Apple", "ticker": "AAPL"}
        }
    }

    with patch(
        "src.workflow.nodes.intent_extraction.nodes.intent_orchestrator.search_candidates",
        side_effect=Exception("Search Error"),
    ):
        command = searching_node(state)

        assert command.goto == "clarifying"
        assert command.update["node_statuses"]["intent_extraction"] == "degraded"
        assert "Search tool failed" in command.update["error_logs"][0]["error"]


@pytest.mark.asyncio
async def test_decision_node_error_degraded_path():
    state = {
        "intent_extraction": {
            "ticker_candidates": [{"symbol": "AAPL", "confidence": 1.0}]
        }
    }

    with patch(
        "src.workflow.nodes.intent_extraction.nodes.intent_orchestrator.parse_candidates",
        side_effect=Exception("Validation Error"),
    ):
        command = decision_node(state)

        assert command.goto == "clarifying"
        assert command.update["node_statuses"]["intent_extraction"] == "degraded"
        assert "Decision logic crashed" in command.update["error_logs"][0]["error"]


@pytest.mark.asyncio
async def test_searching_node_serializes_domain_candidates_to_json():
    state = {
        "user_query": "Valuate GME",
        "intent_extraction": {
            "extracted_intent": {"company_name": "GameStop", "ticker": "GME"}
        },
    }

    candidates = [
        TickerCandidate(symbol="GME", name="GameStop Corp.", confidence=0.98),
        TickerCandidate(symbol="GMED", name="Globus Medical, Inc.", confidence=0.73),
    ]

    with patch(
        "src.workflow.nodes.intent_extraction.nodes.intent_orchestrator.search_candidates",
        return_value=candidates,
    ):
        command = searching_node(state)

    assert command.goto == "deciding"
    serialized = command.update["intent_extraction"]["ticker_candidates"]
    assert isinstance(serialized, list)
    assert serialized[0]["symbol"] == "GME"
    assert serialized[0]["name"] == "GameStop Corp."
    assert serialized[1]["symbol"] == "GMED"
