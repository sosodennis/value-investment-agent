from unittest.mock import AsyncMock, patch

import pytest

from src.workflow.nodes.technical_analysis.nodes import (
    data_fetch_node,
    semantic_translate_node,
    verification_compute_node,
)


@pytest.mark.asyncio
async def test_data_fetch_node_error():
    state = {
        "ticker": "AAPL",
        "intent_extraction": {"resolved_ticker": "AAPL"},
    }

    with patch(
        "src.agents.technical.subdomains.market_data.infrastructure.yahoo_market_data_provider.YahooMarketDataProvider.fetch_ohlcv"
    ) as mock_fetch:
        mock_fetch.side_effect = Exception("YF API Error")

        command = await data_fetch_node(state)

        assert command.update["node_statuses"]["technical_analysis"] == "error"
        assert command.update["internal_progress"]["data_fetch"] == "error"
        assert "Data fetch failed" in command.update["error_logs"][0]["error"]
        assert command.goto == "__end__"


@pytest.mark.asyncio
async def test_verification_compute_node_error_missing_inputs():
    state = {
        "technical_analysis": {
            # Missing timeseries_bundle_id/feature_pack_id/fusion_report_id
        }
    }

    command = await verification_compute_node(state)

    assert command.update["node_statuses"]["technical_analysis"] == "error"
    assert (
        "Missing timeseries/feature/fusion inputs"
        in command.update["error_logs"][0]["error"]
    )
    assert command.goto == "__end__"


@pytest.mark.asyncio
async def test_verification_compute_node_crash():
    state = {
        "technical_analysis": {
            "timeseries_bundle_id": "bundle-1",
            "feature_pack_id": "features-1",
            "fusion_report_id": "fusion-1",
        },
        "intent_extraction": {"resolved_ticker": "AAPL"},
    }

    with patch(
        "src.agents.technical.subdomains.artifacts.infrastructure.technical_artifact_repository.TechnicalArtifactRepository.load_timeseries_bundle",
        new=AsyncMock(side_effect=Exception("Load Error")),
    ):
        command = await verification_compute_node(state)

    assert command.update["node_statuses"]["technical_analysis"] == "error"
    assert "Verification compute failed" in command.update["error_logs"][0]["error"]


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
        "src.agents.technical.application.wiring.assemble_semantic_tags"
    ) as mock_assemble:
        mock_assemble.side_effect = Exception("Assembler Crash")

        command = await semantic_translate_node(state)

        assert command.update["node_statuses"]["technical_analysis"] == "error"
        assert "Semantic translation failed" in command.update["error_logs"][0]["error"]
