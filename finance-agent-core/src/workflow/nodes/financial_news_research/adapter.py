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

    financial_news = sub_output.get("financial_news_research", {})
    artifact = sub_output.get("artifact")
    messages = sub_output.get("messages", [])

    # [Compatibility] Copy flat artifact back to nested context
    if artifact:
        if isinstance(financial_news, dict):
            financial_news["artifact"] = artifact
        else:
            # If it's a Pydantic model (though usually dict in sub_output)
            financial_news.artifact = artifact

    return {
        "financial_news_research": financial_news,
        "messages": messages,
        "node_statuses": {"financial_news_research": "done"},
    }
