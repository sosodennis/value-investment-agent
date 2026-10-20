from unittest.mock import AsyncMock, patch

import pytest

from src.agents.technical.application import wiring as technical_wiring
from src.agents.technical.workflow.nodes import TechnicalNode, build_technical_nodes


@pytest.fixture(autouse=True)
def reset_workflow_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(technical_wiring, "_technical_workflow_runner", None)


def _nodes() -> dict[str, TechnicalNode]:
    runner = technical_wiring.get_technical_workflow_runner()
    return build_technical_nodes(runner)


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

        command = await _nodes()["data_fetch"](state)

        assert command.update["current_node"] == "data_fetch"
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

    command = await _nodes()["verification_compute"](state)

    assert command.update["current_node"] == "verification_compute"
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
        command = await _nodes()["verification_compute"](state)

    assert command.update["current_node"] == "verification_compute"
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

        command = await _nodes()["semantic_translate"](state)

    assert command.update["current_node"] == "semantic_translate"
    assert "Semantic translation failed" in command.update["error_logs"][0]["error"]
