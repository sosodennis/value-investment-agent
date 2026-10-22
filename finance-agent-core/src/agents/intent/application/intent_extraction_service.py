"""
Extraction logic for the Intent agent.
Uses LLM to extract intent (Company, Model Preference) from user query.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from uuid import uuid4

from src.agents.intent.domain.heuristic_intent_policy import heuristic_extract_intent
from src.agents.intent.domain.ticker_candidate import TickerCandidate
from src.agents.intent.interface.contracts import IntentExtraction, SearchExtraction
from src.agents.intent.interface.prompt_specs import (
    build_intent_extraction_system_prompt,
    build_search_extraction_system_prompt,
)
from src.llm_provider.entrypoint import (
    ChatMessage,
    ChatRole,
    CompletionRequest,
    LLMProviderPort,
    ModelRoute,
    StructuredRequest,
)
from src.shared.kernel.tools.logger import bounded_text, get_logger, log_event

logger = get_logger(__name__)


def _heuristic_extract(
    query: str, *, intent_model_factory: Callable[..., IntentExtraction]
) -> IntentExtraction:
    heuristic = heuristic_extract_intent(query)
    return intent_model_factory(
        company_name=heuristic.company_name,
        ticker=heuristic.ticker,
        is_valuation_request=heuristic.is_valuation_request,
        reasoning=heuristic.reasoning,
    )


def extract_candidates_from_search(
    query: str,
    search_results: str,
    *,
    search_extraction_model_type: type[SearchExtraction],
    to_ticker_candidate_fn: Callable[[object], TickerCandidate],
    llm_provider: LLMProviderPort,
    llm_route: ModelRoute,
) -> list[TickerCandidate]:
    """
    Extract potential ticker symbols and company names from search results using LLM.
    """
    try:
        request = CompletionRequest(
            messages=(
                ChatMessage(
                    role=ChatRole.SYSTEM,
                    content=build_search_extraction_system_prompt(),
                ),
                ChatMessage(
                    role=ChatRole.USER,
                    content=(
                        f"User Query: {query}\n\nSearch Results: {search_results}"
                    ),
                ),
            ),
            route=llm_route,
            request_id=f"intent-search-{uuid4().hex}",
            operation="intent.search_extraction",
            timeout_seconds=30.0,
        )
        response = llm_provider.complete_structured(
            StructuredRequest[SearchExtraction](
                completion=request,
                response_schema=search_extraction_model_type,
            )
        )
        candidates_raw = response.candidates
        if not isinstance(candidates_raw, list):
            raise TypeError("search extraction output shape is invalid")
        return [to_ticker_candidate_fn(candidate) for candidate in candidates_raw]
    except Exception as exc:
        log_event(
            logger,
            event="intent_search_extraction_failed",
            message="llm search extraction failed; returning empty candidates",
            level=logging.WARNING,
            error_code="INTENT_SEARCH_EXTRACTION_FAILED",
            fields={"exception": bounded_text(exc)},
        )
        return []


def extract_intent(
    query: str,
    *,
    intent_model_type: type[IntentExtraction],
    llm_provider: LLMProviderPort,
    llm_route: ModelRoute,
) -> IntentExtraction:
    """
    Extract intent from user query using LLM with heuristic resilience path.
    """
    try:
        request = CompletionRequest(
            messages=(
                ChatMessage(
                    role=ChatRole.SYSTEM,
                    content=build_intent_extraction_system_prompt(),
                ),
                ChatMessage(role=ChatRole.USER, content=query),
            ),
            route=llm_route,
            request_id=f"intent-extract-{uuid4().hex}",
            operation="intent.extract",
            timeout_seconds=30.0,
        )
        response = llm_provider.complete_structured(
            StructuredRequest[IntentExtraction](
                completion=request,
                response_schema=intent_model_type,
            )
        )
        dumped = response.model_dump(mode="json")
        if not isinstance(dumped, dict):
            raise TypeError("intent extraction output shape is invalid")
        required_fields = {
            "company_name",
            "ticker",
            "is_valuation_request",
            "reasoning",
        }
        if not required_fields.issubset(dumped.keys()):
            raise TypeError("intent extraction output shape is invalid")
        return response
    except Exception as exc:
        log_event(
            logger,
            event="intent_extraction_failed_fallback_heuristic",
            message="llm intent extraction failed; using heuristic fallback",
            level=logging.WARNING,
            error_code="INTENT_EXTRACTION_FALLBACK_HEURISTIC",
            fields={"exception": bounded_text(exc)},
        )
        return _heuristic_extract(query, intent_model_factory=intent_model_type)
