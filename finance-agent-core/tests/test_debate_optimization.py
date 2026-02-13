from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.workflow.nodes.debate.nodes import debate_aggregator_node, r1_bull_node


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
            "src.workflow.nodes.debate.nodes._prepare_debate_reports",
            new_mock=AsyncMock(),
        ) as mock_prepare,
        patch(
            "src.workflow.nodes.debate.nodes._compress_reports",
            return_value="compressed_data",
        ) as mock_compress,
    ):
        mock_prepare.return_value = {"news": {}, "ta": {}, "fa": {}}

        command = await debate_aggregator_node(state)

        assert "compressed_reports" in command.update
        assert command.update["compressed_reports"] == "compressed_data"
        mock_prepare.assert_called_once()
        mock_compress.assert_called_once()


@pytest.mark.asyncio
async def test_agent_uses_cached_reports():
    state = {
        "ticker": "AAPL",
        "compressed_reports": "cached_data",
        "intent_extraction": {"resolved_ticker": "AAPL"},
        "debate": {"history": []},
        "internal_progress": {},
    }

    with (
        patch(
            "src.workflow.nodes.debate.nodes._prepare_debate_reports",
            new_mock=AsyncMock(),
        ) as mock_prepare,
        patch("src.workflow.nodes.debate.nodes.get_llm") as mock_get_llm,
    ):
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(content="thesis")
        mock_get_llm.return_value = mock_llm

        await r1_bull_node(state)

        # Should NOT call prepare_debate_reports if cache exists
        mock_prepare.assert_not_called()


@pytest.mark.asyncio
async def test_agent_fallbacks_if_no_cache():
    state = {
        "ticker": "AAPL",
        # no compressed_reports
        "intent_extraction": {"resolved_ticker": "AAPL"},
        "debate": {"history": []},
        "internal_progress": {},
    }

    with (
        patch(
            "src.agents.debate.application.report_service.prepare_debate_reports",
            new_mock=AsyncMock(),
        ) as mock_prepare,
        patch(
            "src.agents.debate.application.report_service.compress_reports",
            return_value="data",
        ) as mock_compress,
        patch("src.workflow.nodes.debate.nodes.get_llm") as mock_get_llm,
    ):
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(content="thesis")
        mock_get_llm.return_value = mock_llm
        mock_prepare.return_value = {}

        await r1_bull_node(state)

        # SHOULD call prepare_debate_reports if cache MISSING
        mock_prepare.assert_called_once()
        mock_compress.assert_called_once()
