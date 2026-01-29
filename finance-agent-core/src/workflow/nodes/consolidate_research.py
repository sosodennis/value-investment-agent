import traceback

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
        logger.info(
            "--- Consolidate Research: Framework synchronization complete. Proceeding to debate. ---"
        )

        return Command(
            update={
                "node_statuses": {
                    "consolidate_research": "done",
                }
            },
            goto="prepare_debate",
        )

    except Exception as e:
        logger.error(
            f"❌ consolidate_research_node: ERROR - {type(e).__name__}: {str(e)}"
        )

        logger.error(f"consolidate_research_node: Traceback:\n{traceback.format_exc()}")
        raise
