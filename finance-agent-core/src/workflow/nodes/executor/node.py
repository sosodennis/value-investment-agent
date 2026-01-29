"""
Executor Node - Extracts valuation parameters from financial data.

In production, this would use LLM to extract parameters from 10-K filings,
financial statements, and other sources.
"""

from langchain_core.messages import AIMessage
from langgraph.graph import END
from langgraph.types import Command

from src.interface.schemas import AgentOutputArtifact
from src.utils.logger import get_logger

from ...manager import SkillRegistry
from ...schemas import ExtractionOutput
from ...state import AgentState
from .schemas import ExecutorPreview
from .tools import generate_mock_bank_data, generate_mock_saas_data

logger = get_logger(__name__)


def executor_node(state: AgentState) -> Command:
    """
    Extracts valuation parameters for the selected model type.
    """
    model_type = state.fundamental_analysis.model_type
    logger.info(f"--- Executor: Extracting parameters for {model_type} ---")

    skill = SkillRegistry.get_skill(model_type)
    if not skill:
        raise ValueError(f"Unknown model type: {model_type}")

    schema = skill["schema"]

    # MOCK DATA GENERATION
    if model_type == "saas":
        mock_data = generate_mock_saas_data(state.ticker)
    elif model_type == "bank":
        mock_data = generate_mock_bank_data(state.ticker)
    else:
        raise ValueError(f"Unsupported model type: {model_type}")

    # Validate structure via Pydantic
    try:
        validated = schema(**mock_data)
        # Wrap in ExtractionOutput
        output = ExtractionOutput(params=validated.model_dump())
        return Command(
            update={
                "fundamental_analysis": {"extraction_output": output},
                "artifact": AgentOutputArtifact(
                    summary=f"Extracted parameters for {model_type} analysis.",
                    preview=ExecutorPreview(
                        model_type=model_type,
                        param_count=len(output.params),
                        status="extracted",
                    ).model_dump(),
                    reference=None,  # No heavy data to reference
                ),
                "node_statuses": {"executor": "done", "auditor": "running"},
            },
            goto="auditor",
        )
    except Exception as e:
        logger.error(f"Extraction Failed: {e}")
        return Command(
            update={
                "messages": [
                    AIMessage(
                        content=f"Extraction failed for {model_type}: {e}",
                        additional_kwargs={"agent_id": "executor"},
                    )
                ],
                "node_statuses": {"executor": "error"},
            },
            goto=END,
        )  # Fallback if extraction fails completely
