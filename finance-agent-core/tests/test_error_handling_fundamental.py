from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.workflow.nodes.fundamental_analysis.nodes import (
    financial_health_node,
    model_selection_node,
)


@pytest.mark.asyncio
async def test_financial_health_node_error_log():
    # Simulate a network error during data fetching
    state = {
        "ticker": "AAPL",
        "intent_extraction": {"resolved_ticker": "AAPL"},
    }

    with patch(
        "src.workflow.nodes.fundamental_analysis.nodes.fetch_financial_data"
    ) as mock_fetch:
        mock_fetch.side_effect = Exception("Network Timeout")

        command = await financial_health_node(state)

        assert "error_logs" in command.update
        assert command.update["error_logs"][0]["node"] == "financial_health"
        assert "Network Timeout" in command.update["error_logs"][0]["error"]
        assert command.update["internal_progress"]["financial_health"] == "error"
        assert command.goto == "__end__"


@pytest.mark.asyncio
async def test_model_selection_node_error_log():
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
        "src.workflow.nodes.fundamental_analysis.nodes.select_valuation_model"
    ) as mock_select:
        mock_select.side_effect = Exception("Selection Logic Error")

        command = await model_selection_node(state)

        assert "error_logs" in command.update
        assert command.update["error_logs"][0]["node"] == "model_selection"
        assert "Selection Logic Error" in command.update["error_logs"][0]["error"]
        assert command.update["internal_progress"]["model_selection"] == "error"
        assert command.goto == "__end__"


@pytest.mark.asyncio
async def test_model_selection_node_accepts_canonical_report_shape():
    state = {
        "ticker": "GME",
        "intent_extraction": {
            "resolved_ticker": "GME",
            "company_profile": {
                "ticker": "GME",
                "name": "GameStop Corp.",
                "sector": "Consumer Discretionary",
                "industry": "Specialty Retail",
            },
        },
        "fundamental_analysis": {"financial_reports_artifact_id": "artifact_1"},
    }

    canonical_reports = [
        {
            "base": {
                "fiscal_year": {"value": "2024"},
                "fiscal_period": {"value": "FY"},
                "sic_code": {"value": "5734"},
                "total_revenue": {"value": 3823000000.0},
                "net_income": {"value": 131300000.0},
                "operating_cash_flow": {"value": 145700000.0},
                "total_equity": {"value": 4929800000.0},
                "total_assets": {"value": 5875400000.0},
            },
            "extension_type": "Industrial",
            "extension": {"inventory": {"value": 1.0}},
        }
    ]

    with (
        patch(
            "src.workflow.nodes.fundamental_analysis.nodes.artifact_manager.get_artifact",
            new=AsyncMock(return_value=SimpleNamespace(data=canonical_reports)),
        ),
        patch(
            "src.workflow.nodes.fundamental_analysis.nodes.artifact_manager.save_artifact",
            new=AsyncMock(return_value="artifact_saved"),
        ),
    ):
        command = await model_selection_node(state)

    assert command.goto == "calculation"
    assert "error_logs" not in command.update
