"""
Intent Extraction Nodes.
Handles extraction, searching, decision, and clarification for ticker resolution.
"""

import logging
from collections.abc import Mapping

from langgraph.graph import END
from langgraph.types import Command, interrupt

from src.agents.intent.application.factory import intent_orchestrator
from src.shared.kernel.tools.logger import get_logger, log_event

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
    log_event(
        logger,
        event="intent_clarification_waiting_for_user",
        message="ticker ambiguity detected; waiting for user clarification",
        level=logging.WARNING,
        error_code="INTENT_CLARIFICATION_REQUIRED",
    )

    interrupt_payload_dump, candidates_raw = (
        intent_orchestrator.build_clarification_interrupt_payload(state)
    )
    user_input = interrupt(interrupt_payload_dump)
    payload_keys: list[str] = []
    if isinstance(user_input, Mapping):
        payload_keys = sorted(str(key) for key in user_input.keys())
    log_event(
        logger,
        event="intent_clarification_input_received",
        message="intent clarification input received",
        fields={
            "payload_type": type(user_input).__name__,
            "payload_keys": payload_keys,
        },
    )

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
    log_event(
        logger,
        event="intent_clarification_resolution_failed_retrying",
        message="intent clarification resolution failed; retrying extraction",
        level=logging.WARNING,
        error_code="INTENT_CLARIFICATION_RETRY",
    )
    result = intent_orchestrator.build_clarification_retry_update()
    return Command(update=result.update, goto=result.goto)
