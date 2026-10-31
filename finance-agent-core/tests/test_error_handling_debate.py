from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage

from src.agents.debate.application.debate_service import DEBATE_LLM_TIMEOUT_SECONDS
from src.agents.debate.application.wiring import get_debate_workflow_runner
from src.agents.debate.workflow.graph import _retryable_provider_error
from src.agents.debate.workflow.nodes import build_debate_nodes
from src.llm_provider.entrypoint import LLMErrorCode, LLMProviderError, LLMRequestClass

debate_runner = get_debate_workflow_runner()
debate_nodes = build_debate_nodes(debate_runner)
r1_bull_node = debate_nodes["r1_bull"]
r1_moderator_node = debate_nodes["r1_moderator"]
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
        assert command.update["history"][0].additional_kwargs["round_num"] == 1
        # Error log present
        assert command.update["error_logs"][0]["node"] == "r1_bull"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_code", "retryable"),
    [
        (LLMErrorCode.UPSTREAM_TIMEOUT, True),
        (LLMErrorCode.SCHEMA_VALIDATION_FAILED, False),
    ],
)
async def test_verdict_provider_errors_propagate_with_retryability(
    error_code: LLMErrorCode, retryable: bool
):
    state = {
        "ticker": "AAPL",
        "intent_extraction": {"resolved_ticker": "AAPL"},
        "history": [AIMessage(content="Arg1", name="GrowthHunter")],
    }

    error = LLMProviderError(
        code=error_code,
        provider="litellm",
        model="openrouter-default",
        request_id="verdict-test",
        reason="gateway request failed",
        retryable=retryable,
        attempt=2,
    )
    mock_complete_structured = AsyncMock(side_effect=error)
    with patch.object(
        debate_runner.orchestrator.llm_provider,
        "acomplete_structured",
        new=mock_complete_structured,
    ):
        with pytest.raises(LLMProviderError) as raised:
            await verdict_node(state)

    assert raised.value is error
    assert _retryable_provider_error(raised.value) is retryable
    request = mock_complete_structured.await_args.args[0]
    assert request.completion.request_class is LLMRequestClass.BACKGROUND
    assert request.completion.timeout_seconds == DEBATE_LLM_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_moderator_error_message_keeps_its_round_number():
    with patch(
        "src.agents.debate.application.orchestrator.execute_moderator_round",
        side_effect=Exception("Moderator timeout"),
    ):
        command = await r1_moderator_node(
            {
                "intent_extraction": {"resolved_ticker": "AAPL"},
                "history": [],
            }
        )

    assert command.update["history"][0].name == "Judge"
    assert command.update["history"][0].additional_kwargs["round_num"] == 1
