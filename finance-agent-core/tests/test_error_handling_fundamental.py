from unittest.mock import AsyncMock, patch

import pytest

from src.agents.fundamental.application.wiring import get_fundamental_workflow_runner
from src.agents.fundamental.workflow.nodes import (
    FundamentalNode,
    build_fundamental_nodes,
)


def _fundamental_nodes() -> dict[str, FundamentalNode]:
    return build_fundamental_nodes(get_fundamental_workflow_runner())


@pytest.mark.asyncio
async def test_financial_health_node_waits_for_service_snapshot_without_sec_fetch():
    state = {
        "company_profile": {"ticker": "AAPL", "name": "Apple Inc."},
    }

    with patch(
        "src.agents.fundamental.capabilities.financial_statements.infrastructure.sec_xbrl.extract.financial_payload_service.fetch_financial_reports_payload",
        side_effect=AssertionError("Agent-owned SEC fetch must not run"),
    ):
        command = await _fundamental_nodes()["financial_health"](state)

    assert "error_logs" not in command.update
    assert command.update["workflow_activity_updates"]["financial_health"] == "done"
    assert command.goto == "model_selection"
    context = command.update["fundamental_analysis"]
    assert context["xbrl_diagnostics"]["reason"] == (
        "service_snapshot_request_required"
    )
    assert context["xbrl_quality_gates"]["status"] == "unavailable"
    assert "artifact_references" not in command.update


@pytest.mark.asyncio
async def test_model_selection_node_error_log():
    # Simulate an error in model selection (e.g., missing profile in a way that triggers exception)
    state = {
        "company_profile": {
            "ticker": "AAPL",
            "name": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
        },
    }

    with patch(
        "src.agents.fundamental.application.workflow_orchestrator.factory.select_valuation_model"
    ) as mock_select:
        mock_select.side_effect = Exception("Selection Logic Error")

        command = await _fundamental_nodes()["model_selection"](state)

        assert "error_logs" in command.update
        assert command.update["error_logs"][0]["node"] == "model_selection"
        assert "Selection Logic Error" in command.update["error_logs"][0]["error"]
        assert command.update["workflow_activity_updates"]["model_selection"] == "error"
        assert command.goto == "__end__"


@pytest.mark.asyncio
async def test_model_selection_node_ignores_legacy_report_artifact():
    state = {
        "company_profile": {
            "ticker": "GME",
            "name": "GameStop Corp.",
            "sector": "Consumer Discretionary",
            "industry": "Specialty Retail",
        },
        "fundamental_analysis": {"financial_reports_artifact_id": "artifact_1"},
    }

    with (
        patch(
            "src.agents.fundamental.capabilities.artifacts_provenance.infrastructure.fundamental_artifact_repository.FundamentalArtifactRepository.load_financial_reports_bundle",
            new=AsyncMock(
                side_effect=AssertionError("legacy report load must not run")
            ),
        ),
        patch(
            "src.agents.fundamental.capabilities.artifacts_provenance.infrastructure.fundamental_artifact_repository.FundamentalArtifactRepository.save_financial_reports",
            new=AsyncMock(
                side_effect=AssertionError("legacy report save must not run")
            ),
        ),
    ):
        command = await _fundamental_nodes()["model_selection"](state)

    assert command.goto == "calculation"
    assert "error_logs" not in command.update
    context = command.update["fundamental_analysis"]
    assert context["model_selection_status"] == "degraded"
    assert context["service_facts_status"] == "unavailable"
    assert "financial_reports_artifact_id" not in context
    assert "artifact_references" not in command.update
