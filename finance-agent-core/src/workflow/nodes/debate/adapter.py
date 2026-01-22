from typing import Any

from src.utils.logger import get_logger

from ...state import AgentState
from ..fundamental_analysis.adapter import map_model_to_skill

logger = get_logger(__name__)


def input_adapter(state: AgentState) -> dict[str, Any]:
    """Maps parent AgentState to DebateSubgraphState input."""
    logger.info("--- [Debate Adapter] Mapping parent state to subgraph input ---")
    return {
        "ticker": state.ticker,
        "intent_extraction": state.intent_extraction,
        "fundamental": state.fundamental,
        "financial_news": state.financial_news,
        "technical_analysis": state.technical_analysis,
        "debate": state.debate,
        "messages": state.messages,
        "model_type": state.model_type,
    }


def output_adapter(sub_output: dict[str, Any]) -> dict[str, Any]:
    """Maps DebateSubgraphState output back to parent state updates."""
    logger.info("--- [Debate Adapter] Mapping subgraph output back to parent state ---")

    # Handle model_type update if conclusion reached
    model_type = sub_output.get("model_type")
    debate_ctx = sub_output.get("debate")
    if debate_ctx and debate_ctx.get("conclusion"):
        raw_model = debate_ctx["conclusion"].get("model_type")
        if raw_model:
            model_type = map_model_to_skill(raw_model)

    return {
        "debate": debate_ctx,
        "messages": sub_output.get("messages", []),
        "model_type": model_type,
        "node_statuses": {"debate": "done"},
    }
