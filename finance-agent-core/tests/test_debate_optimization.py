from unittest.mock import AsyncMock, patch

import pytest

from src.agents.debate.application.dto import DebateSourceLoadIssue
from src.agents.debate.application.report_service import PreparedDebateReports
from src.agents.debate.application.wiring import get_debate_workflow_runner
from src.agents.debate.workflow.nodes import build_debate_nodes
from src.shared.llm.contracts import CompletionResult

debate_runner = get_debate_workflow_runner()
debate_nodes = build_debate_nodes(debate_runner)
debate_aggregator_node = debate_nodes["debate_aggregator"]
r1_bull_node = debate_nodes["r1_bull"]


@pytest.mark.asyncio
async def test_debate_aggregator_caches_reports():
    # Mock pre-requisites
    state = {
        "intent_extraction": {"resolved_ticker": "AAPL"},
        "financial_news_research": {},
        "technical_analysis": {},
        "fundamental_analysis": {},
    }

    with (
        patch(
            "src.agents.debate.application.orchestrator.prepare_debate_reports",
            new=AsyncMock(),
        ) as mock_prepare,
        patch(
            "src.agents.debate.application.orchestrator.DebateOrchestrator._compress_reports",
            return_value="compressed_data",
        ) as mock_compress,
    ):
        mock_prepare.return_value = PreparedDebateReports(
            payload={"news": {}, "ta": {}, "fa": {}},
            load_issues=[],
        )

        command = await debate_aggregator_node(state)

        assert "context_summary_text" in command.update
        assert command.update["context_summary_text"] == "compressed_data"
        assert command.update["internal_progress"]["debate_aggregator"] == "done"
        assert command.update["internal_progress"]["r1_bull"] == "running"
        mock_prepare.assert_called_once()
        mock_compress.assert_called_once()


@pytest.mark.asyncio
async def test_debate_aggregator_exposes_degraded_source_state() -> None:
    state = {
        "intent_extraction": {"resolved_ticker": "AAPL"},
        "financial_news_research": {},
        "technical_analysis": {},
        "fundamental_analysis": {},
    }
    with (
        patch(
            "src.agents.debate.application.orchestrator.prepare_debate_reports",
            new=AsyncMock(),
        ) as mock_prepare,
        patch(
            "src.agents.debate.application.orchestrator.DebateOrchestrator._compress_reports",
            return_value="compressed_data",
        ),
    ):
        mock_prepare.return_value = PreparedDebateReports(
            payload={"news": {}, "ta": {}, "fa": {}},
            load_issues=[
                DebateSourceLoadIssue(
                    artifact="news",
                    status="artifact_not_found",
                    artifact_id="news-1",
                )
            ],
        )
        command = await debate_aggregator_node(state)

    assert command.update["internal_progress"]["debate_aggregator"] == "done"
    assert command.update["error_logs"][0]["node"] == "debate_aggregator"
    assert "degraded source inputs" in command.update["error_logs"][0]["error"]


@pytest.mark.asyncio
async def test_agent_uses_cached_reports():
    state = {
        "ticker": "AAPL",
        "context_summary_text": "cached_data",
        "facts_registry_text": "FACTS_REGISTRY (STRICT CITATION REQUIRED):\n[F001] data",
        "intent_extraction": {"resolved_ticker": "AAPL"},
        "debate": {"history": []},
        "internal_progress": {},
    }

    with (
        patch(
            "src.agents.debate.application.report_service.prepare_debate_reports",
            new=AsyncMock(),
        ) as mock_prepare,
        patch.object(
            debate_runner.orchestrator.llm_provider,
            "acomplete",
            new=AsyncMock(
                return_value=CompletionResult(
                    request_id="test-debate",
                    text="thesis",
                    model="openrouter/auto",
                )
            ),
        ),
    ):
        await r1_bull_node(state)

        # Should NOT call prepare_debate_reports if cache exists
        mock_prepare.assert_not_called()


@pytest.mark.asyncio
async def test_agent_fallbacks_if_no_cache():
    state = {
        "ticker": "AAPL",
        # no context_summary_text
        "intent_extraction": {"resolved_ticker": "AAPL"},
        "debate": {"history": []},
        "internal_progress": {},
    }

    with (
        patch(
            "src.agents.debate.application.report_service.prepare_debate_reports",
            new=AsyncMock(),
        ) as mock_prepare,
        patch(
            "src.agents.debate.application.report_service.compress_reports",
            return_value="data",
        ) as mock_compress,
        patch.object(
            debate_runner.orchestrator.llm_provider,
            "acomplete",
            new=AsyncMock(
                return_value=CompletionResult(
                    request_id="test-debate",
                    text="thesis",
                    model="openrouter/auto",
                )
            ),
        ),
    ):
        mock_prepare.return_value = PreparedDebateReports(payload={}, load_issues=[])

        await r1_bull_node(state)

        # SHOULD call prepare_debate_reports if cache MISSING
        mock_prepare.assert_called_once()
        mock_compress.assert_called_once()
