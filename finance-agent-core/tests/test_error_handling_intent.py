from unittest.mock import patch

import pytest

from src.workflow.nodes.intent_extraction.nodes import (
    decision_node,
    extraction_node,
    searching_node,
)


@pytest.mark.asyncio
async def test_extraction_node_error_fallback():
    state = {"user_query": "Analyze Apple"}

    with patch(
        "src.workflow.nodes.intent_extraction.nodes.extract_intent",
        side_effect=Exception("LLM Error"),
    ):
        command = extraction_node(state)

        assert command.goto == "clarifying"
        assert command.update["node_statuses"]["intent_extraction"] == "degraded"
        assert (
            "Model failed to extract intent" in command.update["error_logs"][0]["error"]
        )


@pytest.mark.asyncio
async def test_searching_node_error_fallback():
    state = {
        "intent_extraction": {
            "extracted_intent": {"company_name": "Apple", "ticker": "AAPL"}
        }
    }

    with patch(
        "src.workflow.nodes.intent_extraction.nodes.search_ticker",
        side_effect=Exception("Search Error"),
    ):
        command = searching_node(state)

        assert command.goto == "clarifying"
        assert command.update["node_statuses"]["intent_extraction"] == "degraded"
        assert "Search tool failed" in command.update["error_logs"][0]["error"]


@pytest.mark.asyncio
async def test_decision_node_error_fallback():
    state = {
        "intent_extraction": {
            "ticker_candidates": [{"symbol": "AAPL", "confidence": 1.0}]
        }
    }

    with patch(
        "src.workflow.nodes.intent_extraction.nodes.TickerCandidate",
        side_effect=Exception("Validation Error"),
    ):
        command = decision_node(state)

        assert command.goto == "clarifying"
        assert command.update["node_statuses"]["intent_extraction"] == "degraded"
        assert "Decision logic crashed" in command.update["error_logs"][0]["error"]
