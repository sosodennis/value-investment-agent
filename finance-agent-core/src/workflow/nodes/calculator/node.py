"""
Calculator Node - Executes deterministic valuation calculations.

This is a simple wrapper around the SkillRegistry calculator functions.
"""

from langchain_core.messages import AIMessage
from langgraph.graph import END
from langgraph.types import Command

from src.interface.schemas import AgentOutputArtifact

from ...manager import SkillRegistry
from ...schemas import CalculationOutput
from ...state import AgentState
from .schemas import CalculatorSuccess


def calculation_node(state: AgentState) -> Command:
    """
    Executes the deterministic valuation calculation.
    """
    print("--- Calculator: Running Deterministic Engine ---")

    try:
        extraction_output = state.fundamental_analysis.extraction_output
        if isinstance(extraction_output, dict):
            params_dict = extraction_output.get("params", {})
        else:
            params_dict = extraction_output.params

        model_type = state.fundamental_analysis.model_type
        skill = SkillRegistry.get_skill(model_type)

        if not skill:
            raise ValueError(f"Skill not found for model type: {model_type}")

        schema = skill["schema"]
        calc_func = skill["calculator"]

        params_obj = schema(**params_dict)
        result = calc_func(params_obj)

        print("✅ Valuation Logic Complete. Returning result to Conversation.")

        # Prepare artifact
        artifact = AgentOutputArtifact(
            summary=f"Valuation Complete. Model: {model_type}",
            data=CalculatorSuccess(metrics=result, model_type=model_type).model_dump(),
        )

        return Command(
            update={
                "fundamental_analysis": {
                    "calculation_output": CalculationOutput(metrics=result),
                    # Persist artifact so it shows up on page reload
                    "artifact": artifact,
                },
                # Fix: Update node_statuses at the top level, not inside fundamental_analysis
                "node_statuses": {"calculator": "done"},
                # Keep artifact at top level for immediate event emission (Flat Pattern)
                "artifact": artifact,
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
