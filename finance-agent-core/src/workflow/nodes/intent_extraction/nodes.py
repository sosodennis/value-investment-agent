"""
Intent Extraction Nodes.
Handles extraction, searching, decision, and clarification for ticker resolution.
"""

from langgraph.graph import END
from langgraph.types import Command, interrupt

from src.agents.intent.application.factory import intent_orchestrator
from src.shared.kernel.tools.logger import get_logger

from .subgraph_state import IntentExtractionState

logger = get_logger(__name__)


def _resolve_goto(goto: str) -> str:
    return END if goto == "END" else goto


def extraction_node(state: IntentExtractionState) -> Command:
    """Extract company and model from user query."""
    result = intent_orchestrator.run_extraction(state)
    return Command(update=result.update, goto=_resolve_goto(result.goto))


def searching_node(state: IntentExtractionState) -> Command:
    """Search for the ticker based on extracted intent."""
    result = intent_orchestrator.run_searching(state)
    return Command(update=result.update, goto=_resolve_goto(result.goto))


def decision_node(state: IntentExtractionState) -> Command:
    """Decide if ticker is resolved or needs clarification."""
    result = intent_orchestrator.run_decision(state)
    return Command(update=result.update, goto=_resolve_goto(result.goto))


def clarification_node(state: IntentExtractionState) -> Command:
    """
    Triggers an interrupt to ask the user to select a ticker or provide clarification.
    """
    logger.warning(
        "--- Intent Extraction: Ticker Ambiguity Detected. Waiting for user input... ---"
    )

    interrupt_payload_dump, candidates_raw = (
        intent_orchestrator.build_clarification_interrupt_payload(state)
    )
    user_input = interrupt(interrupt_payload_dump)
    logger.info(f"--- Intent Extraction: Received user input: {user_input} ---")

    resolution_update = intent_orchestrator.build_clarification_resolution_update(
        user_input=user_input,
        candidates_raw=candidates_raw,
        interrupt_payload_dump=interrupt_payload_dump,
    )
    if resolution_update is not None:
        return Command(
            update=resolution_update,
            goto=END,
        )

    # If even fallback fails, retry extraction
    logger.warning("--- Intent Extraction: Resolution failed, retrying extraction ---")
    result = intent_orchestrator.build_clarification_retry_update()
    return Command(update=result.update, goto=result.goto)
