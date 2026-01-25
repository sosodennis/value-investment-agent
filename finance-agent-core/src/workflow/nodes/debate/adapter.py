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
        "model_type": state.fundamental_analysis.model_type,
    }


def output_adapter(sub_output: dict[str, Any]) -> dict[str, Any]:
    """Maps DebateState output back to parent state updates."""
    logger.info("--- [Debate Adapter] Mapping subgraph output back to parent state ---")

    debate_ctx = sub_output.get("debate", {})
    messages = sub_output.get("messages", [])
    model_type = sub_output.get("model_type")

    # Extract model_type from debate conclusion if available
    if isinstance(debate_ctx, dict) and debate_ctx.get("artifact"):
        artifact = debate_ctx["artifact"]
        data = (
            artifact.get("data")
            if isinstance(artifact, dict)
            else getattr(artifact, "data", None)
        )
        if data:
            raw_model = (
                data.get("model_type")
                if isinstance(data, dict)
                else getattr(data, "model_type", None)
            )
            if raw_model:
                model_type = map_model_to_skill(raw_model)

    # Update FundamentalAnalysisContext with the decided model_type
    # This ensures the Executor knows which model to run
    fundamental_update = {}
    if model_type:
        fundamental_update["model_type"] = model_type

    return {
        "debate": debate_ctx,
        "fundamental_analysis": fundamental_update,
        "messages": messages,
        "node_statuses": {"debate": "done"},
    }
