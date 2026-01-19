import traceback

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
    try:
        logger.info("=== [DEBUG] consolidate_research_node: Starting ===")
        logger.info(f"[DEBUG] consolidate_research_node: state type = {type(state)}")
        logger.info(
            f"[DEBUG] consolidate_research_node: AgentState module = {AgentState.__module__}"
        )

        fa_status = state.node_statuses.get("fundamental_analysis", "idle")
        news_status = state.node_statuses.get("financial_news_research", "idle")
        ta_status = state.node_statuses.get("technical_analysis", "idle")

        logger.info(
            f"--- Consolidate Research: FA={fa_status}, News={news_status}, TA={ta_status} ---"
        )

        # Check if all three are done
        if fa_status == "done" and news_status == "done" and ta_status == "done":
            logger.info(
                "--- Consolidate Research: Both branches complete, proceeding to debate ---"
            )
            logger.info(
                "[DEBUG] consolidate_research_node: Creating Command to goto debate"
            )
            return Command(
                update={
                    "node_statuses": {
                        "consolidate_research": "done",
                        "debate": "running",
                    }
                },
                goto="debate",
            )

        # If any is still running or not started, wait
        # Don't update any statuses here to avoid race conditions
        logger.info(
            "--- Consolidate Research: Waiting for all 3 parallel branches to complete ---"
        )
        logger.info("[DEBUG] consolidate_research_node: Creating Command to goto END")
        return Command(
            update={"node_statuses": {"consolidate_research": "waiting"}},
            goto=END,
        )
    except Exception as e:
        logger.error(
            f"❌ [DEBUG] consolidate_research_node: ERROR - {type(e).__name__}: {str(e)}"
        )

        logger.error(
            f"[DEBUG] consolidate_research_node: Traceback:\n{traceback.format_exc()}"
        )
        raise
