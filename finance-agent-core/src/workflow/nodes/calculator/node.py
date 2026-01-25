"""
Calculator Node - Executes deterministic valuation calculations.

This is a simple wrapper around the SkillRegistry calculator functions.
"""

from langchain_core.messages import AIMessage
from langgraph.graph import END
from langgraph.types import Command

from ...manager import SkillRegistry
from ...schemas import CalculationOutput
from ...state import AgentState


def calculation_node(state: AgentState) -> Command:
    """
    Executes the deterministic valuation calculation.
    """
    print("--- Calculator: Running Deterministic Engine ---")

    try:
        if not state.fundamental_analysis.extraction_output:
            raise ValueError("No extraction output found in state")

        params_dict = state.fundamental_analysis.extraction_output.params
        model_type = state.fundamental_analysis.model_type
        skill = SkillRegistry.get_skill(model_type)

        schema = skill["schema"]
        calc_func = skill["calculator"]

        params_obj = schema(**params_dict)

        result = calc_func(params_obj)

        # Format the result nicely
        msg_content = (
            f"### Valuation Complete\n\n**Model**: {model_type}\n**Result**: {result}"
        )

        print("✅ Valuation Logic Complete. Returning result to Conversation.")

        return Command(
            update={
                "calculation_output": CalculationOutput(metrics=result),
                "messages": [
                    AIMessage(
                        content=msg_content,
                        additional_kwargs={"agent_id": "calculator"},
                    )
                ],
                "node_statuses": {"calculator": "done"},
            },
            goto=END,
        )
    except Exception as e:
        print(f"Calculation Failed: {e}")
        return Command(
            update={
                "messages": [
                    AIMessage(
                        content=f"Calculation failed: {e}",
                        additional_kwargs={"agent_id": "calculator"},
                    )
                ],
                "node_statuses": {"calculator": "error"},
            },
            goto=END,
        )
