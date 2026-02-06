"""
Executor Node - Extracts valuation parameters from financial data.
"""

from langgraph.graph import END
from langgraph.types import Command

from src.common.utils.logger import get_logger
from src.interface.schemas import AgentOutputArtifact

from ...manager import SkillRegistry
from ...schemas import ExtractionOutput
from .mappers import summarize_executor_for_preview
from .subgraph_state import ExecutorState
from .tools import generate_mock_bank_data, generate_mock_saas_data

logger = get_logger(__name__)


def executor_node(state: ExecutorState) -> Command:
    """
    Extracts valuation parameters for the selected model type.
    """
    fundamental = state.get("fundamental_analysis", {})
    model_type = fundamental.get("model_type")
    ticker = state.get("ticker")
    logger.info(f"--- Executor: Extracting parameters for {model_type} ---")

    try:
        skill = SkillRegistry.get_skill(model_type)
        if not skill:
            raise ValueError(f"Unknown model type: {model_type}")

        schema = skill["schema"]

        # MOCK DATA GENERATION
        if model_type == "saas":
            mock_data = generate_mock_saas_data(ticker)
        elif model_type == "bank":
            mock_data = generate_mock_bank_data(ticker)
        else:
            raise ValueError(f"Unsupported model type: {model_type}")

        validated = schema(**mock_data)
        # Wrap in ExtractionOutput
        output = ExtractionOutput(params=validated.model_dump())

        preview = summarize_executor_for_preview(output.model_dump(), model_type)
        artifact = AgentOutputArtifact(
            summary=f"Extracted parameters for {model_type} analysis.",
            preview=preview,
            reference=None,
        )

        fa_update = fundamental.copy()
        fa_update["extraction_output"] = output
        fa_update["artifact"] = artifact

        return Command(
            update={
                "fundamental_analysis": fa_update,
                "current_node": "executor",
                "node_statuses": {"executor": "done"},
            },
            goto=END,
        )
    except Exception as e:
        logger.error(f"Extraction Failed: {e}", exc_info=True)
        return Command(
            update={
                "error_logs": [
                    {
                        "node": "executor",
                        "error": str(e),
                        "severity": "error",
                    }
                ],
                "node_statuses": {"executor": "error"},
            },
            goto=END,
        )
