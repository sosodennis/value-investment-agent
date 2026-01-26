from typing import Any

from pydantic import TypeAdapter

from src.utils.logger import get_logger

from ...state import AgentState
from .schemas import TechnicalAnalysisResult

logger = get_logger(__name__)


def input_adapter(state: AgentState) -> dict[str, Any]:
    """Maps parent AgentState to TechnicalAnalysisState input."""
    logger.info(
        f"--- [TA Adapter] Mapping parent state to subgraph input for {state.ticker} ---"
    )
    return {
        "ticker": state.ticker,
        "intent_extraction": state.intent_extraction,
        "technical_analysis": state.technical_analysis,
    }


def output_adapter(sub_output: dict[str, Any]) -> dict[str, Any]:
    """Maps TechnicalAnalysisState output back to parent state updates."""
    logger.info("--- [TA Adapter] Mapping subgraph output back to parent state ---")

    # 1. Validate with TypeAdapter
    validator = TypeAdapter(TechnicalAnalysisResult)
    ta_ctx = sub_output.get("technical_analysis", {})

    # Validate artifact data if present
    artifact_wrapper = ta_ctx.get("artifact")
    if artifact_wrapper:
        raw_data = (
            artifact_wrapper.data
            if hasattr(artifact_wrapper, "data")
            else artifact_wrapper.get("data")
        )
        if raw_data:
            try:
                model = validator.validate_python(raw_data)
                logger.info(
                    f"✅ [TA Adapter] Output validated as {type(model).__name__}"
                )
            except Exception as e:
                logger.error(f"❌ [TA Adapter] Output validation failed: {e}")
                raise e

    # The artifact should be in the technical_analysis context
    # but we don't need to extract it here anymore as it's passed via ta_ctx dict/model

    return {
        "technical_analysis": ta_ctx,
        "messages": sub_output.get("messages", []),
        "node_statuses": {"technical_analysis": "done"},
    }
