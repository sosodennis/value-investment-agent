from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage

from src.agents.debate.application.wiring import get_debate_workflow_runner
from src.agents.debate.workflow.nodes import build_debate_nodes
from src.llm_provider.entrypoint import LLMErrorCode, LLMProviderError

debate_runner = get_debate_workflow_runner()
debate_nodes = build_debate_nodes(debate_runner)
r1_bull_node = debate_nodes["r1_bull"]
verdict_node = debate_nodes["verdict"]


@pytest.mark.asyncio
async def test_r1_bull_node_error_resilience():
    state = {
        "ticker": "AAPL",
        "intent_extraction": {"resolved_ticker": "AAPL"},
    }

    with patch(
        "src.agents.debate.application.orchestrator.execute_bull_round"
    ) as mock_exec:
        mock_exec.side_effect = Exception("Bull Agent Timeout")

        command = await r1_bull_node(state)

        # Should continue to moderator
        assert command.goto == "r1_moderator"
        # Status should be degraded
        assert command.update["workflow_activity_updates"]["r1_bull"] == "error"
        # History should have phantom message
        assert "Bull Agent failed" in command.update["history"][0].content
        assert "[SYSTEM]" in command.update["history"][0].content
        # Error log present
        assert command.update["error_logs"][0]["node"] == "r1_bull"


@pytest.mark.asyncio
async def test_verdict_node_error_log():
    state = {
        "ticker": "AAPL",
        "intent_extraction": {"resolved_ticker": "AAPL"},
        "history": [AIMessage(content="Arg1", name="GrowthHunter")],
    }

    error = LLMProviderError(
        code=LLMErrorCode.UPSTREAM_UNAVAILABLE,
        provider="litellm-gateway",
        model="openrouter-default",
        request_id="verdict-test",
        reason="gateway request failed",
        retryable=False,
        attempt=2,
    )
    with patch.object(
        debate_runner.orchestrator.llm_provider,
        "acomplete_structured",
        new=AsyncMock(side_effect=error),
    ):
        command = await verdict_node(state)

        # Should end workflow
        assert command.goto == "__end__"
        # Status should be error
        assert command.update["workflow_activity_updates"]["verdict"] == "error"
        # Error log present
        assert "Verdict generation failed" in command.update["error_logs"][0]["error"]
