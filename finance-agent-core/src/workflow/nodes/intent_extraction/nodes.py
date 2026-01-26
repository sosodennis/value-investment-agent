"""
Intent Extraction Nodes.
Handles extraction, searching, decision, and clarification for ticker resolution.
"""

from langgraph.types import Command, interrupt

from src.interface.schemas import AgentOutputArtifact
from src.utils.logger import get_logger

from ..fundamental_analysis.extraction import (
    IntentExtraction,
    deduplicate_candidates,
    extract_candidates_from_search,
    extract_intent,
)
from ..fundamental_analysis.logic import should_request_clarification
from ..fundamental_analysis.structures import TickerCandidate
from ..fundamental_analysis.tools import get_company_profile, search_ticker, web_search
from .schemas import IntentExtractionSuccess
from .subgraph_state import IntentExtractionState

logger = get_logger(__name__)


def extraction_node(state: IntentExtractionState) -> Command:
    """Extract company and model from user query."""
    user_query = state.user_query
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
    intent = extract_intent(user_query)
    return Command(
        update={
            "intent_extraction": {
                "extracted_intent": intent.model_dump(),
                "status": "searching",
            },
            "current_node": "extraction",
            "internal_progress": {"extraction": "done", "searching": "running"},
        },
        goto="searching",
    )


def searching_node(state: IntentExtractionState) -> Command:
    """Search for the ticker based on extracted intent."""
    intent = state.intent_extraction.extracted_intent or {}

    # Extract explicit fields
    extracted_ticker = intent.get("ticker")
    extracted_name = intent.get("company_name")

    # === Multi-Query Strategy ===
    search_queries = []

    # 1. Company Name (Broad Match) - Priorities catching multiple share classes (GOOG vs GOOGL)
    if extracted_name:
        search_queries.append(extracted_name)

    # 2. Ticker (Exact Match) - Add if distinct from name
    if extracted_ticker and extracted_ticker != extracted_name:
        search_queries.append(extracted_ticker)

    # If explicit extraction failed, fallback to the raw query (heuristic)
    if not search_queries:
        if state.user_query:
            # Basic heuristic cleanup
            clean_query = (
                state.user_query.replace("Valuate", "").replace("Value", "").strip()
            )
            search_queries.append(clean_query)
        else:
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
    candidate_map = {}

    # === Execute Search on All Queries ===
    for query in search_queries:
        # 1. Try Yahoo Finance Search
        yf_candidates = search_ticker(query)

        # Check for high confidence matches
        high_confidence_candidates = [c for c in yf_candidates if c.confidence >= 0.9]
        if high_confidence_candidates:
            logger.info(
                f"--- Intent Extraction: High confidence match found via Yahoo for '{query}': {[c.symbol for c in high_confidence_candidates]} ---"
            )

        for c in yf_candidates:
            # Deduplicate by symbol
            if c.symbol not in candidate_map:
                candidate_map[c.symbol] = c
            else:
                # Merge: Keep the one with higher confidence
                if c.confidence > candidate_map[c.symbol].confidence:
                    candidate_map[c.symbol] = c

    # 2. Web Search fallback (Always run to ensure coverage)
    # Use the primary query (Name or Ticker) for web search
    primary_query = search_queries[0]
    # Use quotes to force exact match and reduce noise
    search_results = web_search(f'"{primary_query}" stock ticker symbol official')

    web_candidates = extract_candidates_from_search(primary_query, search_results)

    for c in web_candidates:
        if c.symbol in candidate_map:
            if c.confidence > candidate_map[c.symbol].confidence:
                candidate_map[c.symbol] = c
        else:
            candidate_map[c.symbol] = c

    final_candidates = deduplicate_candidates(list(candidate_map.values()))
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


def decision_node(state: IntentExtractionState) -> Command:
    """Decide if ticker is resolved or needs clarification."""
    candidates = state.intent_extraction.ticker_candidates or []

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

    # Check for ambiguity
    candidate_objs = [TickerCandidate(**c) for c in candidates]

    if should_request_clarification(candidate_objs):
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
    profile = get_company_profile(resolved_ticker)

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

    return Command(
        update={
            "intent_extraction": {
                "resolved_ticker": resolved_ticker,
                "company_profile": profile.model_dump(),
                "status": "resolved",
            },
            "artifact": AgentOutputArtifact(
                summary=f"Resolved Ticker: {resolved_ticker} ({profile.name})",
                data=IntentExtractionSuccess(
                    resolved_ticker=resolved_ticker,
                    company_profile=profile.model_dump(),
                    status="resolved",
                ).model_dump(),
            ),
            "ticker": resolved_ticker,
            "current_node": "deciding",
            "internal_progress": {"deciding": "done"},
        },
        goto=END,
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
    interrupt_payload = HumanTickerSelection(
        candidates=state.intent_extraction.ticker_candidates or [],
        intent=IntentExtraction(**state.intent_extraction.extracted_intent)
        if state.intent_extraction.extracted_intent
        else None,
        reason="Multiple tickers found or ambiguity detected.",
    )
    user_input = interrupt(interrupt_payload.model_dump())
    logger.info(f"--- Intent Extraction: Received user input: {user_input} ---")

    # user_input is what the frontend sends back, e.g. { "selected_symbol": "GOOGL" }
    selected_symbol = user_input.get("selected_symbol") or user_input.get("ticker")

    if not selected_symbol:
        # Fallback to top candidate if resumed without choice
        candidates = state.intent_extraction.ticker_candidates or []
        if candidates:
            top = candidates[0]
            selected_symbol = top.get("symbol") if isinstance(top, dict) else top.symbol

    if selected_symbol:
        logger.info(
            f"✅ User selected or fallback symbol: {selected_symbol}. Resolving..."
        )
        profile = get_company_profile(selected_symbol)
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

            return Command(
                update={
                    "intent_extraction": {
                        "resolved_ticker": selected_symbol,
                        "company_profile": profile.model_dump(),
                        "status": "resolved",
                    },
                    "artifact": AgentOutputArtifact(
                        summary=f"Manually Resolved Ticker: {selected_symbol} ({profile.name})",
                        data=IntentExtractionSuccess(
                            resolved_ticker=selected_symbol,
                            company_profile=profile.model_dump(),
                            status="resolved",
                        ).model_dump(),
                    ),
                    "ticker": selected_symbol,
                    "messages": new_messages,
                    "current_node": "clarifying",
                    "internal_progress": {"clarifying": "done"},
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
