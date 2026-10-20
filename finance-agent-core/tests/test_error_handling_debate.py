from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from src.agents.debate.application.wiring import get_debate_workflow_runner
from src.agents.debate.workflow.nodes import build_debate_nodes

debate_nodes = build_debate_nodes(get_debate_workflow_runner())
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
        assert command.update["internal_progress"]["r1_bull"] == "error"
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

    with patch("src.agents.debate.application.wiring.get_llm") as mock_llm:
        # Simulate LLM failure
        mock_chain = MagicMock()
        mock_chain.ainvoke.side_effect = Exception("Verdict Generation Error")

        mock_struct_llm = MagicMock()
        mock_struct_llm.ainvoke.side_effect = Exception("Verdict Generation Error")
        mock_llm.return_value.with_structured_output.return_value = mock_struct_llm

        command = await verdict_node(state)

        # Should end workflow
        assert command.goto == "__end__"
        # Status should be error
        assert command.update["internal_progress"]["verdict"] == "error"
        # Error log present
        assert "Verdict generation failed" in command.update["error_logs"][0]["error"]
