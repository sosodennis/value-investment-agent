import os
import sys

# Put app root in path
sys.path.insert(0, os.getcwd())

from src.workflow.nodes.debate.adapter import input_adapter
from src.workflow.state import AgentState


def test_debate_adapter_fix():
    # Create state without model_type at top level
    state = AgentState()
    # It has fundamental_analysis, which should have model_type
    state.fundamental_analysis.model_type = "bank"
    state.ticker = "JPM"

    try:
        # Run adapter
        result = input_adapter(state)
        print("✅ Adapter ran successfully")
        print(f"Result model_type: {result.get('model_type')}")

        assert (
            result.get("model_type") == "bank"
        ), "Failed to extract model_type from FA context"

    except AttributeError as e:
        print(f"❌ Adapter failed with AttributeError: {e}")
    except Exception as e:
        print(f"❌ Adapter failed with {type(e).__name__}: {e}")


if __name__ == "__main__":
    test_debate_adapter_fix()
