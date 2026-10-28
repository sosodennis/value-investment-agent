from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.debate.application.debate_service import execute_moderator_round
from src.agents.debate.application.dto import DebateSourceLoadIssue
from src.agents.debate.application.report_service import PreparedDebateReports
from src.agents.debate.application.wiring import get_debate_workflow_runner
from src.agents.debate.workflow.nodes import build_debate_nodes
from src.llm_provider.entrypoint import CompletionResult

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
        assert (
            command.update["workflow_activity_updates"]["debate_aggregator"] == "done"
        )
        assert command.update["workflow_activity_updates"]["r1_bull"] == "running"
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

    assert command.update["workflow_activity_updates"]["debate_aggregator"] == "done"
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
        "workflow_activity_updates": {},
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
        command = await r1_bull_node(state)

        # Should NOT call prepare_debate_reports if cache exists
        mock_prepare.assert_not_called()
        assert command.update["history"][0].additional_kwargs["round_num"] == 1


@pytest.mark.asyncio
async def test_moderator_history_exposes_its_round_number():
    state = {
        "intent_extraction": {"resolved_ticker": "AAPL"},
        "history": [],
        "bull_thesis": "Revenue growth remains durable.",
        "bear_thesis": "Valuation limits upside.",
        "context_summary_text": "Cached debate context.",
        "facts_registry_text": "Cached evidence.",
    }
    provider = MagicMock()
    provider.acomplete = AsyncMock(
        return_value=CompletionResult(
            request_id="test-moderator-round",
            text="The bear case raises a material valuation risk.",
            model="openrouter/auto",
        )
    )
    detector = MagicMock()
    detector.check_consensus.return_value = (0.2, False)

    result = await execute_moderator_round(
        state=state,
        round_num=2,
        system_prompt_template="{ticker}\n{facts_registry}\n{context_summary}",
        llm_provider=provider,
        llm_route=debate_runner.orchestrator.llm_route,
        detector=detector,
        source_reader=debate_runner.orchestrator.source_reader,
    )

    assert result["history"][0].name == "Judge"
    assert result["history"][0].additional_kwargs["round_num"] == 2


@pytest.mark.asyncio
async def test_agent_fallbacks_if_no_cache():
    state = {
        "ticker": "AAPL",
        # no context_summary_text
        "intent_extraction": {"resolved_ticker": "AAPL"},
        "debate": {"history": []},
        "workflow_activity_updates": {},
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
