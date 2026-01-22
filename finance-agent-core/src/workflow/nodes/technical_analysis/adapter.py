from typing import Any

from src.utils.logger import get_logger

from ...state import AgentState

logger = get_logger(__name__)


def input_adapter(state: AgentState) -> dict[str, Any]:
    """Maps parent AgentState to TechnicalAnalysisSubgraphState input."""
    logger.info(
        f"--- [TA Adapter] Mapping parent state to subgraph input for {state.ticker} ---"
    )
    return {
        "ticker": state.ticker,
        "intent_extraction": state.intent_extraction,
        "technical_analysis": state.technical_analysis,
    }


def output_adapter(sub_output: dict[str, Any]) -> dict[str, Any]:
    """Maps TechnicalAnalysisSubgraphState output back to parent state updates."""
    logger.info("--- [TA Adapter] Mapping subgraph output back to parent state ---")
    return {
        "technical_analysis": sub_output.get("technical_analysis"),
        "messages": sub_output.get("messages", []),
        "node_statuses": {"technical_analysis": "done"},
    }
