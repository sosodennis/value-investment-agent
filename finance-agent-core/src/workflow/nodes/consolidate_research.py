"""
Consolidate Research Node.
Synchronizes parallel branches (fundamental_analysis and financial_news_research).
"""

from langgraph.graph import END
from langgraph.types import Command

from src.utils.logger import get_logger

from ..state import AgentState

logger = get_logger(__name__)


def consolidate_research_node(state: AgentState) -> Command:
    """
    Synchronize parallel research branches before debate.
    Waits for both fundamental_analysis and financial_news_research to complete.
    This node acts as a barrier/join point for parallel execution.
    """
    fa_status = state.node_statuses.get("fundamental_analysis", "idle")
    news_status = state.node_statuses.get("financial_news_research", "idle")

    logger.info(f"--- Consolidate Research: FA={fa_status}, News={news_status} ---")

    # Check if both are done
    if fa_status == "done" and news_status == "done":
        logger.info(
            "--- Consolidate Research: Both branches complete, proceeding to debate ---"
        )
        return Command(
            update={
                "node_statuses": {"consolidate_research": "done", "debate": "running"}
            },
            goto="debate",
        )

    # If either is still running or not started, wait
    # Don't update any statuses here to avoid race conditions
    logger.info(
        "--- Consolidate Research: Waiting for parallel branches to complete ---"
    )
    return Command(
        update={"node_statuses": {"consolidate_research": "waiting"}},
        goto=END,
    )
