from typing import Any

from pydantic import TypeAdapter

from src.utils.logger import get_logger

from ...state import AgentState
from .schemas import FinancialNewsResult

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

    # 1. Validate with TypeAdapter
    validator = TypeAdapter(FinancialNewsResult)
    financial_news = sub_output.get("financial_news_research", {})

    # Validate artifact data if present
    artifact_wrapper = financial_news.get("artifact")
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
                    f"✅ [News Adapter] Output validated as {type(model).__name__}"
                )
            except Exception as e:
                logger.error(f"❌ [News Adapter] Output validation failed: {e}")
                raise e

    # The artifact should be in the financial_news_research context
    # but we don't need to extract it here anymore as it's passed via financial_news dict/model

    messages = sub_output.get("messages", [])

    return {
        "financial_news_research": financial_news,
        "messages": messages,
        "node_statuses": {"financial_news_research": "done"},
    }
