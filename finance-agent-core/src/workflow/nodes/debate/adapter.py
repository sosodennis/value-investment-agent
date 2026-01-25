from typing import Any

from src.utils.logger import get_logger

from ...state import AgentState
from ..fundamental_analysis.adapter import map_model_to_skill

logger = get_logger(__name__)


def input_adapter(state: AgentState) -> dict[str, Any]:
    """Maps parent AgentState to DebateState input."""
    logger.info("--- [Debate Adapter] Mapping parent state to subgraph input ---")
    return {
        "ticker": state.ticker,
        "intent_extraction": state.intent_extraction,
        "fundamental_analysis": state.fundamental_analysis,
        "financial_news_research": state.financial_news_research,
        "technical_analysis": state.technical_analysis,
        "debate": state.debate,
        "messages": state.messages,
        "model_type": state.model_type,
    }


def output_adapter(sub_output: dict[str, Any]) -> dict[str, Any]:
    """Maps DebateState output back to parent state updates."""
    logger.info("--- [Debate Adapter] Mapping subgraph output back to parent state ---")

    debate_ctx = sub_output.get("debate", {})
    artifact = sub_output.get("artifact")
    messages = sub_output.get("messages", [])
    model_type = sub_output.get("model_type")

    # [Compatibility] Copy flat artifact back to nested context
    if artifact:
        if isinstance(debate_ctx, dict):
            debate_ctx["artifact"] = artifact
        else:
            debate_ctx.artifact = artifact

        # Handle model_type update if conclusion reached
        data = artifact.data if hasattr(artifact, "data") else artifact.get("data")
        if data:
            raw_model = data.get("model_type")
            if raw_model:
                model_type = map_model_to_skill(raw_model)

    return {
        "debate": debate_ctx,
        "messages": messages,
        "model_type": model_type,
        "node_statuses": {"debate": "done"},
    }
