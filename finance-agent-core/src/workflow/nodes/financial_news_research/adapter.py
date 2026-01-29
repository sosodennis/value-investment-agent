from typing import Any

from src.interface.schemas import AgentOutputArtifact, ArtifactReference
from src.utils.logger import get_logger

from ...state import AgentState
from .mappers import summarize_news_for_preview

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
    """
    Maps FinancialNewsState output back to parent state updates.
    Uses mapper to generate preview data per Engineering Charter v3.1.
    """
    logger.info("--- [News Adapter] Mapping subgraph output back to parent state ---")

    # Get the context from subgraph output
    # Since it's a TypedDict, sub_output is a root state dict
    financial_news_ctx = sub_output.get("financial_news_research", {})

    # 1. Generate preview using mapper from metadata in context
    try:
        # Mapper will use top_headlines from context if news_items is empty (which it is)
        preview = summarize_news_for_preview(financial_news_ctx)

        # 2. Construct L3 Reference if report_id exists
        report_id = financial_news_ctx.get("report_id")
        reference = None
        if report_id:
            reference = ArtifactReference(
                artifact_id=report_id,
                download_url=f"/api/artifacts/{report_id}",
                type="news_analysis_report",
            )

        # 3. Construct AgentOutputArtifact (L1, L2, L3)
        artifact = AgentOutputArtifact(
            summary=f"新聞分析: {preview['sentiment_display']}",
            preview=preview,
            reference=reference,
        )

        # 4. Attach artifact to context
        # Note: Even if 'artifact' is not in the TypedDict schema,
        # NodeOutputMapper looks for it, and LangGraph allows it.
        financial_news_ctx["artifact"] = artifact

        logger.info(f"✅ [News Adapter] Created preview and reference for {report_id}")

    except Exception as e:
        logger.error(f"❌ [News Adapter] Failed to generate preview: {e}")

    messages = sub_output.get("messages", [])

    return {
        "financial_news_research": financial_news_ctx,
        "messages": messages,
        "node_statuses": {"financial_news_research": "done"},
    }
