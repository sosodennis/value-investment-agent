from typing import Any

from src.utils.logger import get_logger

from ...state import AgentState

logger = get_logger(__name__)


def input_adapter(state: AgentState) -> dict[str, Any]:
    """Maps parent AgentState to IntentExtractionState input."""
    logger.info("--- [Intent Adapter] Mapping parent state to subgraph input ---")
    return {
        "ticker": state.ticker,
        "user_query": state.user_query,
        "messages": state.messages,
        "intent_extraction": state.intent_extraction,
    }


def output_adapter(sub_output: dict[str, Any]) -> dict[str, Any]:
    """Maps IntentExtractionState output back to parent state updates."""
    logger.info("--- [Intent Adapter] Mapping subgraph output back to parent state ---")
    return {
        "intent_extraction": sub_output.get("intent_extraction"),
        "ticker": sub_output.get("ticker"),  # Intent extraction resolves ticker
        "messages": sub_output.get("messages", []),
        "node_statuses": {"intent_extraction": "done"},
    }
