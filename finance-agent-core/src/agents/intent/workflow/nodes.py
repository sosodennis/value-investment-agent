from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping

from langgraph.graph import END
from langgraph.types import Command, interrupt

from src.agents.intent.application.orchestrator import IntentOrchestrator
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.workflow_routing import resolve_end_goto

from .state import IntentExtractionState

logger = get_logger(__name__)
IntentNode = Callable[[IntentExtractionState], Awaitable[Command]]


def build_intent_nodes(orchestrator: IntentOrchestrator) -> dict[str, IntentNode]:
    async def extraction_node(state: IntentExtractionState) -> Command:
        result = await asyncio.to_thread(orchestrator.run_extraction, state)
        return Command(
            update=result.update, goto=resolve_end_goto(result.goto, end_node=END)
        )

    async def searching_node(state: IntentExtractionState) -> Command:
        result = await asyncio.to_thread(orchestrator.run_searching, state)
        return Command(
            update=result.update, goto=resolve_end_goto(result.goto, end_node=END)
        )

    async def decision_node(state: IntentExtractionState) -> Command:
        result = await asyncio.to_thread(orchestrator.run_decision, state)
        return Command(
            update=result.update, goto=resolve_end_goto(result.goto, end_node=END)
        )

    async def clarification_node(state: IntentExtractionState) -> Command:
        log_event(
            logger,
            event="intent_clarification_waiting_for_user",
            message="ticker ambiguity detected; waiting for user clarification",
            level=logging.WARNING,
            error_code="INTENT_CLARIFICATION_REQUIRED",
        )
        interrupt_payload_dump, candidates_raw = (
            orchestrator.build_clarification_interrupt_payload(state)
        )
        candidate_count = len(candidates_raw) if isinstance(candidates_raw, list) else 0
        user_input = interrupt(interrupt_payload_dump)
        payload_keys = (
            sorted(str(key) for key in user_input.keys())
            if isinstance(user_input, Mapping)
            else []
        )
        log_event(
            logger,
            event="intent_clarification_input_received",
            message="intent clarification input received",
            fields={
                "payload_type": type(user_input).__name__,
                "payload_keys": payload_keys,
            },
        )
        resolution_update = orchestrator.build_clarification_resolution_update(
            user_input=user_input,
            candidates_raw=candidates_raw,
        )
        if resolution_update is not None:
            intent_ctx_raw = resolution_update.get("intent_extraction")
            resolved_ticker = None
            if isinstance(intent_ctx_raw, Mapping):
                ticker = intent_ctx_raw.get("resolved_ticker")
                if isinstance(ticker, str) and ticker.strip():
                    resolved_ticker = ticker
            log_event(
                logger,
                event="intent_clarification_completed",
                message="intent clarification completed",
                fields={
                    "status": "resolved",
                    "goto_node": "END",
                    "is_degraded": False,
                    "candidate_count": candidate_count,
                    "resolved_ticker": resolved_ticker,
                },
            )
            return Command(update=resolution_update, goto=END)

        log_event(
            logger,
            event="intent_clarification_resolution_failed_retrying",
            message="intent clarification resolution failed; retrying extraction",
            level=logging.WARNING,
            error_code="INTENT_CLARIFICATION_RETRY",
        )
        log_event(
            logger,
            event="intent_clarification_completed",
            message="intent clarification completed",
            level=logging.WARNING,
            error_code="INTENT_CLARIFICATION_RETRY",
            fields={
                "status": "retry_extraction",
                "goto_node": "extraction",
                "is_degraded": True,
                "candidate_count": candidate_count,
                "resolved_ticker": None,
            },
        )
        result = await asyncio.to_thread(orchestrator.build_clarification_retry_update)
        return Command(
            update=result.update, goto=resolve_end_goto(result.goto, end_node=END)
        )

    return {
        "extraction": extraction_node,
        "searching": searching_node,
        "deciding": decision_node,
        "clarifying": clarification_node,
    }
