"""
Calculator Node - Executes deterministic valuation calculations.
"""

from langgraph.graph import END
from langgraph.types import Command

from src.common.tools.logger import get_logger
from src.interface.schemas import AgentOutputArtifact

from ...manager import SkillRegistry
from .mappers import summarize_calculator_for_preview
from .structures import CalculationOutput
from .subgraph_state import CalculatorState

logger = get_logger(__name__)


def calculation_node(state: CalculatorState) -> Command:
    """
    Executes the deterministic valuation calculation.
    """
    logger.info("--- Calculator: Running Deterministic Engine ---")

    try:
        fundamental = state.get("fundamental_analysis", {})
        extraction_output = fundamental.get("extraction_output")
        if isinstance(extraction_output, dict):
            params_dict = extraction_output.get("params", {})
        elif extraction_output:
            params_dict = extraction_output.params
        else:
            params_dict = {}

        model_type = fundamental.get("model_type")
        skill = SkillRegistry.get_skill(model_type)

        if not skill:
            raise ValueError(f"Skill not found for model type: {model_type}")

        schema = skill["schema"]
        calc_func = skill["calculator"]

        params_obj = schema(**params_dict)
        result = calc_func(params_obj)

        logger.info("✅ Valuation Logic Complete. Returning result to Conversation.")

        calc_output = CalculationOutput(metrics=result)
        preview = summarize_calculator_for_preview(result, model_type)
        artifact = AgentOutputArtifact(
            summary=f"Valuation Complete. Model: {model_type}",
            preview=preview,
            reference=None,
        )

        fa_update = fundamental.copy()
        fa_update["calculation_output"] = calc_output
        fa_update["artifact"] = artifact

        return Command(
            update={
                "fundamental_analysis": fa_update,
                "current_node": "calculator",
                "node_statuses": {"calculator": "done"},
                "artifact": artifact,
            },
            goto=END,
        )
    except Exception as e:
        logger.error(f"Calculation Failed: {e}", exc_info=True)
        return Command(
            update={
                "error_logs": [
                    {
                        "node": "calculator",
                        "error": str(e),
                        "severity": "error",
                    }
                ],
                "node_statuses": {"calculator": "error"},
            },
            goto=END,
        )
