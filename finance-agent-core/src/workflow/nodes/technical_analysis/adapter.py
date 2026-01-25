from typing import Any

from src.utils.logger import get_logger

from ...state import AgentState

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

    # Extract the technical_analysis context from subgraph output
    ta_ctx = sub_output.get("technical_analysis", {})

    # The artifact should be in the technical_analysis context
    # but we don't need to extract it here anymore as it's passed via ta_ctx dict/model

    return {
        "technical_analysis": ta_ctx,
        "messages": sub_output.get("messages", []),
        "node_statuses": {"technical_analysis": "done"},
    }
