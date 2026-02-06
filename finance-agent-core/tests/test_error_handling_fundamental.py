from unittest.mock import patch

from src.workflow.nodes.fundamental_analysis.graph import (
    financial_health_node,
    model_selection_node,
)


def test_financial_health_node_error_log():
    # Simulate a network error during data fetching
    state = {
        "ticker": "AAPL",
        "intent_extraction": {"resolved_ticker": "AAPL"},
    }

    with patch(
        "src.workflow.nodes.fundamental_analysis.graph.fetch_financial_data"
    ) as mock_fetch:
        mock_fetch.side_effect = Exception("Network Timeout")

        command = financial_health_node(state)

        assert "error_logs" in command.update
        assert command.update["error_logs"][0]["node"] == "financial_health"
        assert "Network Timeout" in command.update["error_logs"][0]["error"]
        assert command.update["internal_progress"]["financial_health"] == "error"
        assert command.goto == "__end__"


def test_model_selection_node_error_log():
    # Simulate an error in model selection (e.g., missing profile in a way that triggers exception)
    state = {
        "ticker": "AAPL",
        "intent_extraction": {
            "resolved_ticker": "AAPL",
            "company_profile": {
                "ticker": "AAPL",
                "name": "Apple Inc.",
                "sector": "Technology",
                "industry": "Consumer Electronics",
            },
        },
    }

    with patch(
        "src.workflow.nodes.fundamental_analysis.graph.select_valuation_model"
    ) as mock_select:
        mock_select.side_effect = Exception("Selection Logic Error")

        # model_selection_node is async
        import asyncio

        command = asyncio.run(model_selection_node(state))

        assert "error_logs" in command.update
        assert command.update["error_logs"][0]["node"] == "model_selection"
        assert "Selection Logic Error" in command.update["error_logs"][0]["error"]
        assert command.update["internal_progress"]["model_selection"] == "error"
        assert command.goto == "__end__"
