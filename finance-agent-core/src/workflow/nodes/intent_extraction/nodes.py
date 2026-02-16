"""
Intent Extraction Nodes.
Handles extraction, searching, decision, and clarification for ticker resolution.
"""

from collections.abc import Mapping

from langgraph.types import Command, interrupt

from src.agents.intent.application.orchestrator import IntentOrchestrator
from src.agents.intent.application.use_cases import (
    deduplicate_candidates,
    extract_candidates_from_search,
    extract_intent,
)
from src.agents.intent.data.market_clients import (
    get_company_profile,
    search_ticker,
    web_search,
)
from src.agents.intent.domain.policies import should_request_clarification
from src.agents.intent.interface.contracts import IntentExtraction, SearchExtraction
from src.agents.intent.interface.mappers import (
    summarize_intent_for_preview,
    to_ticker_candidate,
)
from src.agents.intent.interface.parsers import (
    parse_resume_selection_input,
    parse_ticker_candidates,
)
from src.interface.events.schemas import build_artifact_payload
from src.shared.kernel.contracts import OUTPUT_KIND_INTENT_EXTRACTION
from src.shared.kernel.tools.logger import get_logger

from .subgraph_state import IntentExtractionState

logger = get_logger(__name__)


def _build_intent_output_artifact(
    summary: str, preview: dict[str, object]
) -> dict[str, object]:
    return build_artifact_payload(
        kind=OUTPUT_KIND_INTENT_EXTRACTION,
        summary=summary,
        preview=preview,
        reference=None,
    )


intent_orchestrator = IntentOrchestrator(
    extract_intent_fn=lambda query: extract_intent(
        query, intent_model_type=IntentExtraction
    ),
    search_ticker_fn=search_ticker,
    web_search_fn=web_search,
    extract_candidates_from_search_fn=lambda query,
    search_results: extract_candidates_from_search(
        query,
        search_results,
        search_extraction_model_type=SearchExtraction,
        to_ticker_candidate_fn=to_ticker_candidate,
    ),
    deduplicate_candidates_fn=deduplicate_candidates,
    should_request_clarification_fn=should_request_clarification,
    get_company_profile_fn=get_company_profile,
    parse_ticker_candidates_fn=parse_ticker_candidates,
    parse_resume_selection_input_fn=parse_resume_selection_input,
    summarize_preview_fn=summarize_intent_for_preview,
    build_output_artifact_fn=_build_intent_output_artifact,
)


def extraction_node(state: IntentExtractionState) -> Command:
    """Extract company and model from user query."""
    user_query = state.get("user_query")
    if not user_query:
        logger.warning(
            "--- Intent Extraction: No query provided, requesting clarification ---"
        )
        return Command(
            update={
                "intent_extraction": {
                    "status": "clarifying",
                },
                "current_node": "extraction",
                "internal_progress": {"extraction": "done", "clarifying": "running"},
            },
            goto="clarifying",
        )

    logger.info(f"--- Intent Extraction: Extracting intent from: {user_query} ---")
    try:
        intent = intent_orchestrator.extract_intent(user_query)
        return Command(
            update={
                "intent_extraction": {
                    "extracted_intent": intent.model_dump(),
                    "status": "searching",
                },
                "current_node": "extraction",
                "internal_progress": {"extraction": "done", "searching": "running"},
                "node_statuses": {"intent_extraction": "running"},
            },
            goto="searching",
        )
    except Exception as e:
        logger.error(f"Intent extraction failed: {e}")
        return Command(
            update={
                "intent_extraction": {"status": "clarifying"},
                "current_node": "extraction",
                "internal_progress": {"extraction": "error", "clarifying": "running"},
                "node_statuses": {"intent_extraction": "degraded"},
                "error_logs": [
                    {
                        "node": "extraction",
                        "error": f"Model failed to extract intent: {str(e)}",
                        "severity": "error",
                    }
                ],
            },
            goto="clarifying",
        )


def searching_node(state: IntentExtractionState) -> Command:
    """Search for the ticker based on extracted intent."""
    intent_ctx = state.get("intent_extraction", {})
    intent = intent_ctx.get("extracted_intent") or {}
    search_queries = intent_orchestrator.build_search_queries(
        extracted_ticker=intent.get("ticker") if isinstance(intent, Mapping) else None,
        extracted_name=(
            intent.get("company_name") if isinstance(intent, Mapping) else None
        ),
        user_query=state.get("user_query"),
    )
    if not search_queries:
        logger.warning(
            "--- Intent Extraction: Search query missing, requesting clarification ---"
        )
        return Command(
            update={
                "intent_extraction": {"status": "clarifying"},
                "current_node": "searching",
                "internal_progress": {"searching": "done", "clarifying": "running"},
            },
            goto="clarifying",
        )

    logger.info(f"--- Intent Extraction: Searching for queries: {search_queries} ---")

    try:
        final_candidates = intent_orchestrator.search_candidates(search_queries)
        logger.info(f"Final candidates: {[c.symbol for c in final_candidates]}")

        return Command(
            update={
                "intent_extraction": {
                    "ticker_candidates": [c.model_dump() for c in final_candidates],
                    "status": "deciding",
                },
                "current_node": "searching",
                "internal_progress": {"searching": "done", "deciding": "running"},
            },
            goto="deciding",
        )
    except Exception as e:
        logger.error(f"Ticker search failed: {e}")
        return Command(
            update={
                "intent_extraction": {"status": "clarifying"},
                "current_node": "searching",
                "internal_progress": {"searching": "error", "clarifying": "running"},
                "node_statuses": {"intent_extraction": "degraded"},
                "error_logs": [
                    {
                        "node": "searching",
                        "error": f"Search tool failed: {str(e)}. Switching to manual selection.",
                        "severity": "error",
                    }
                ],
            },
            goto="clarifying",
        )


def decision_node(state: IntentExtractionState) -> Command:
    """Decide if ticker is resolved or needs clarification."""
    intent_ctx = state.get("intent_extraction", {})
    candidates = intent_ctx.get("ticker_candidates") or []

    if not candidates:
        logger.warning(
            "--- Intent Extraction: No candidates found, requesting clarification ---"
        )
        return Command(
            update={
                "intent_extraction": {"status": "clarifying"},
                "current_node": "deciding",
                "internal_progress": {"deciding": "done", "clarifying": "running"},
            },
            goto="clarifying",
        )

    try:
        candidate_objs = intent_orchestrator.parse_candidates(candidates)
        if intent_orchestrator.needs_clarification(candidate_objs):
            logger.warning(
                "--- Intent Extraction: Ambiguity detected, requesting clarification ---"
            )
            return Command(
                update={
                    "intent_extraction": {"status": "clarifying"},
                    "current_node": "deciding",
                    "internal_progress": {"deciding": "done", "clarifying": "running"},
                },
                goto="clarifying",
            )

        # Resolved - proceed to set resolved ticker
        resolved_ticker = candidate_objs[0].symbol
        logger.info(f"--- Intent Extraction: Ticker resolved to {resolved_ticker} ---")
        profile = intent_orchestrator.resolve_profile(resolved_ticker)

        if not profile:
            logger.warning(
                f"--- Intent Extraction: Could not fetch profile for {resolved_ticker}, requesting clarification ---"
            )
            return Command(
                update={
                    "intent_extraction": {"status": "clarifying"},
                    "current_node": "deciding",
                    "internal_progress": {"deciding": "done", "clarifying": "running"},
                },
                goto="clarifying",
            )

        from langgraph.graph import END

        intent_ctx = intent_orchestrator.build_resolved_intent_context(
            ticker=resolved_ticker,
            profile=profile,
        )
        artifact = intent_orchestrator.build_output_artifact(
            resolved_ticker=resolved_ticker, intent_ctx=intent_ctx
        )
        intent_ctx["artifact"] = artifact

        return Command(
            update={
                "intent_extraction": intent_ctx,
                "ticker": resolved_ticker,
                "current_node": "deciding",
                "internal_progress": {"deciding": "done"},
                "node_statuses": {"intent_extraction": "done"},
            },
            goto=END,
        )
    except Exception as e:
        logger.error(f"Decision logic failed: {e}")
        return Command(
            update={
                "intent_extraction": {"status": "clarifying"},
                "current_node": "deciding",
                "internal_progress": {"deciding": "error", "clarifying": "running"},
                "node_statuses": {"intent_extraction": "degraded"},
                "error_logs": [
                    {
                        "node": "deciding",
                        "error": f"Decision logic crashed: {str(e)}. Switching to manual selection.",
                        "severity": "error",
                    }
                ],
            },
            goto="clarifying",
        )


def clarification_node(state: IntentExtractionState) -> Command:
    """
    Triggers an interrupt to ask the user to select a ticker or provide clarification.
    """
    logger.warning(
        "--- Intent Extraction: Ticker Ambiguity Detected. Waiting for user input... ---"
    )

    from ...interrupts import HumanTickerSelection

    # Trigger interrupt with candidates
    intent_ctx = state.get("intent_extraction", {})
    extracted_intent = intent_ctx.get("extracted_intent")

    candidates_raw = intent_ctx.get("ticker_candidates") or []

    interrupt_payload = HumanTickerSelection(
        candidates=candidates_raw,
        intent=IntentExtraction(**extracted_intent) if extracted_intent else None,
        reason="Multiple tickers found or ambiguity detected.",
    )
    user_input = interrupt(interrupt_payload.model_dump())
    logger.info(f"--- Intent Extraction: Received user input: {user_input} ---")

    # user_input is what the frontend sends back, e.g. { "selected_symbol": "GOOGL" }
    candidate_objs = intent_orchestrator.parse_candidates(candidates_raw)
    selected_symbol = intent_orchestrator.resolve_selected_symbol(
        user_input=user_input,
        candidate_objs=candidate_objs,
    )

    if selected_symbol:
        logger.info(
            f"✅ User selected or fallback symbol: {selected_symbol}. Resolving..."
        )
        profile = intent_orchestrator.resolve_profile(selected_symbol)
        if profile:
            from langchain_core.messages import AIMessage, HumanMessage
            from langgraph.graph import END

            # Persist interactive messages to history
            new_messages = [
                AIMessage(
                    content="",
                    additional_kwargs={
                        "type": "ticker_selection",
                        "data": interrupt_payload.model_dump(),
                        "agent_id": "intent_extraction",
                    },
                ),
                HumanMessage(content=f"Selected Ticker: {selected_symbol}"),
            ]

            intent_ctx = intent_orchestrator.build_resolved_intent_context(
                ticker=selected_symbol,
                profile=profile,
            )
            artifact = intent_orchestrator.build_output_artifact(
                resolved_ticker=selected_symbol,
                intent_ctx=intent_ctx,
            )
            intent_ctx["artifact"] = artifact

            return Command(
                update={
                    "intent_extraction": intent_ctx,
                    "ticker": selected_symbol,
                    "messages": new_messages,
                    "current_node": "clarifying",
                    "internal_progress": {"clarifying": "done"},
                    "node_statuses": {"intent_extraction": "done"},
                },
                goto=END,
            )

    # If even fallback fails, retry extraction
    logger.warning("--- Intent Extraction: Resolution failed, retrying extraction ---")
    return Command(
        update={
            "intent_extraction": {"status": "extraction"},
            "current_node": "clarifying",
            "internal_progress": {"clarifying": "done", "extraction": "running"},
        },
        goto="extraction",
    )
