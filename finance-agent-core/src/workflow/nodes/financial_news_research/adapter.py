from typing import Any

from src.utils.logger import get_logger

from ...state import AgentState

logger = get_logger(__name__)


def input_adapter(state: AgentState) -> dict[str, Any]:
    """Maps parent AgentState to FinancialNewsState input."""
    logger.info(
        f"--- [News Adapter] Mapping parent state to subgraph input for {state.ticker} ---"
    )
    return {
        "ticker": state.ticker,
        "intent_extraction": state.intent_extraction,
        "financial_news_research": state.financial_news_research,
    }


def output_adapter(sub_output: dict[str, Any]) -> dict[str, Any]:
    """Maps FinancialNewsState output back to parent state updates."""
    logger.info("--- [News Adapter] Mapping subgraph output back to parent state ---")

    # Extract the financial_news_research context from subgraph output
    financial_news = sub_output.get("financial_news_research", {})
    messages = sub_output.get("messages", [])

    # The artifact should be in the financial_news_research context
    # but we don't need to extract it here anymore as it's passed via financial_news dict/model

    return {
        "financial_news_research": financial_news,
        "messages": messages,
        "node_statuses": {"financial_news_research": "done"},
    }
