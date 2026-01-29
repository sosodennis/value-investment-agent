from typing import Any

from src.interface.schemas import AgentOutputArtifact
from src.utils.logger import get_logger

from ...state import AgentState
from .mappers import summarize_intent_for_preview

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

    intent_ctx = sub_output.get("intent_extraction", {})

    # 1. Generate L2 Preview using Mapper
    preview = summarize_intent_for_preview(intent_ctx)

    # 2. Construct Standardized AgentOutputArtifact
    # Use status to determine summary text
    status = intent_ctx.get("status")
    resolved_ticker = intent_ctx.get("resolved_ticker")

    if status == "resolved" and resolved_ticker:
        summary = f"已確認分析標的: {resolved_ticker}"
    elif status == "clarifying":
        summary = "需要更多資訊以確認標的"
    else:
        summary = "正在進行意圖解析..."

    artifact = AgentOutputArtifact(
        summary=summary,
        preview=preview,
        reference=None,  # No L3 cold data for Intent Extraction
    )

    # 3. Inject artifact into context
    intent_ctx["artifact"] = artifact

    return {
        "intent_extraction": intent_ctx,
        "ticker": sub_output.get("ticker"),  # Intent extraction resolves ticker
        "messages": sub_output.get("messages", []),
        "node_statuses": {"intent_extraction": "done"},
    }
