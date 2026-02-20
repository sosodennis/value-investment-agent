import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.workflow.nodes.debate.nodes import verdict_node
from src.workflow.nodes.fundamental_analysis.nodes import model_selection_node


@pytest.mark.anyio
async def test_immediate_status_emission():
    """
    Verify that terminal nodes inside subgraphs emit node_statuses.
    """

    # 1. Test Debate Verdict Node
    print("--- Testing Debate Verdict Node ---")
    mock_debate_state = MagicMock()
    mock_debate_state.intent_extraction.resolved_ticker = "AAPL"
    mock_debate_state.debate.history = []

    # Mock LLM to avoid API calls
    with patch("src.agents.debate.application.factory.get_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm

        # Mock structured output
        mock_struct = MagicMock()
        mock_llm.with_structured_output.return_value = mock_struct

        # Make ainvoke return a coroutine
        async def async_return_conclusion(*args, **kwargs):
            mock_conc = MagicMock()
            mock_conc.model_dump.return_value = {
                "winner": "Bull",
                "confidence": 0.9,
                "reasoning": "Strong growth",
                "bull_score": 90,
                "bear_score": 10,
            }
            return mock_conc

        mock_struct.ainvoke.side_effect = async_return_conclusion

        # Mock simple ainvoke for logs if needed (though verdict uses structured)
        mock_llm.ainvoke.side_effect = async_return_conclusion

        # Call node (it's async)
        result = await verdict_node(mock_debate_state)

        # Handle Command object if returned
        update = result.update if hasattr(result, "update") else result

        if "node_statuses" in update and update["node_statuses"] == {"debate": "done"}:
            print("✅ Debate Verdict emits immediate status")
        else:
            print(f"❌ Debate Verdict FAILED to emit status. Got: {update.keys()}")

    # 2. Test FA Model Selection Node
    print("\n--- Testing FA Model Selection Node ---")
    mock_fa_state = MagicMock()
    mock_fa_state.intent_extraction.resolved_ticker = "AAPL"
    mock_fa_state.intent_extraction.company_profile = {
        "name": "Apple",
        "sector": "Tech",
        "industry": "Consumer Electronics",
        "ticker": "AAPL",
    }
    mock_fa_state.fundamental.financial_reports = []  # Empty list for simplicity

    # model_selection_node returns a Command object
    # We need to inspect command.update

    result = await model_selection_node(mock_fa_state)

    # Command object has .update attribute
    if hasattr(result, "update"):
        update = result.update
        if "node_statuses" in update and update["node_statuses"] == {
            "fundamental_analysis": "done"
        }:
            print("✅ FA Model Selection emits immediate status")
        else:
            print(
                f"❌ FA Model Selection FAILED to emit status. Update keys: {update.keys()}"
            )
    else:
        print("❌ FA Node did not return a Command object")


if __name__ == "__main__":
    asyncio.run(test_immediate_status_emission())
