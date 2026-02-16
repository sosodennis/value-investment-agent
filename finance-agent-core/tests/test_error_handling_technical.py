from unittest.mock import patch

import pytest

from src.workflow.nodes.technical_analysis.nodes import (
    data_fetch_node,
    fracdiff_compute_node,
    semantic_translate_node,
)


@pytest.mark.asyncio
async def test_data_fetch_node_error():
    state = {
        "ticker": "AAPL",
        "intent_extraction": {"resolved_ticker": "AAPL"},
    }

    with patch(
        "src.agents.technical.application.factory.fetch_daily_ohlcv"
    ) as mock_fetch:
        mock_fetch.side_effect = Exception("YF API Error")

        command = await data_fetch_node(state)

        assert command.update["node_statuses"]["technical_analysis"] == "error"
        assert command.update["internal_progress"]["data_fetch"] == "error"
        assert "Data fetch failed" in command.update["error_logs"][0]["error"]
        assert command.goto == "__end__"


@pytest.mark.asyncio
async def test_fracdiff_compute_node_error_missing_artifact():
    state = {
        "technical_analysis": {
            # Missing price_artifact_id
        }
    }

    command = await fracdiff_compute_node(state)

    assert command.update["node_statuses"]["technical_analysis"] == "error"
    assert "Missing price artifact ID" in command.update["error_logs"][0]["error"]
    assert command.goto == "__end__"


@pytest.mark.asyncio
async def test_fracdiff_compute_node_crash():
    state = {"technical_analysis": {"price_artifact_id": "p1"}}

    with patch(
        "src.services.artifact_manager.artifact_manager.get_artifact_data"
    ) as mock_get:
        mock_get.return_value = {
            "price_series": {"2021-01-01": 100.0},
            "volume_series": {"2021-01-01": 1000.0},
        }

        with patch(
            "src.agents.technical.application.factory.calculate_rolling_fracdiff"
        ) as mock_calc:
            mock_calc.side_effect = Exception("Math Error")

            command = await fracdiff_compute_node(state)

            assert command.update["node_statuses"]["technical_analysis"] == "error"
            assert "Computation crashed" in command.update["error_logs"][0]["error"]


@pytest.mark.asyncio
async def test_semantic_translate_node_error():
    state = {
        "technical_analysis": {
            "optimal_d": 0.5,
            "z_score_latest": 1.5,
            "price_artifact_id": "p1",
            "chart_data_id": "c1",
        },
        "intent_extraction": {"resolved_ticker": "AAPL"},
    }

    # Simulate Assembler Crash
    with patch(
        "src.agents.technical.application.factory.assemble_semantic_tags"
    ) as mock_assemble:
        mock_assemble.side_effect = Exception("Assembler Crash")

        command = await semantic_translate_node(state)

        assert command.update["node_statuses"]["technical_analysis"] == "error"
        assert "Semantic translation failed" in command.update["error_logs"][0]["error"]
