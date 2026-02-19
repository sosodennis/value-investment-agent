import logging

from langgraph.types import Command

from src.shared.kernel.tools.logger import get_logger, log_event

from ..state import AgentState

logger = get_logger(__name__)


def consolidate_research_node(state: AgentState) -> Command:
    """
    Synchronize parallel research branches before debate.
    Waits for both fundamental_analysis and financial_news_research to complete.
    This node acts as a barrier/join point for parallel execution.
    """
    try:
        log_event(
            logger,
            event="workflow_consolidate_research_completed",
            message="consolidate research completed; proceeding to debate",
        )

        return Command(
            update={
                "node_statuses": {
                    "consolidate_research": "done",
                }
            },
            goto="debate_agent",
        )

    except Exception as exc:
        log_event(
            logger,
            event="workflow_consolidate_research_failed",
            message="consolidate research failed",
            level=logging.ERROR,
            error_code="WORKFLOW_CONSOLIDATE_RESEARCH_FAILED",
            fields={"exception": str(exc), "exception_type": type(exc).__name__},
        )
        raise
