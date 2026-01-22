from typing import Any

from src.utils.logger import get_logger

from ...state import AgentState

logger = get_logger(__name__)


def input_adapter(state: AgentState) -> dict[str, Any]:
    """Maps parent AgentState to FinancialNewsSubgraphState input."""
    logger.info(
        f"--- [News Adapter] Mapping parent state to subgraph input for {state.ticker} ---"
    )
    return {
        "ticker": state.ticker,
        "intent_extraction": state.intent_extraction,
        "financial_news": state.financial_news,
    }


def output_adapter(sub_output: dict[str, Any]) -> dict[str, Any]:
    """Maps FinancialNewsSubgraphState output back to parent state updates."""
    logger.info("--- [News Adapter] Mapping subgraph output back to parent state ---")
    return {
        "financial_news": sub_output.get("financial_news"),
        "messages": sub_output.get("messages", []),
        "node_statuses": {"financial_news_research": "done"},
    }
