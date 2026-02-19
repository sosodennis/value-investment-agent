"""
Extraction logic for the Intent agent.
Uses LLM to extract intent (Company, Model Preference) from user query.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Protocol

from dotenv import find_dotenv, load_dotenv

from src.agents.intent.domain.extraction_policies import heuristic_extract_intent
from src.agents.intent.domain.models import TickerCandidate
from src.agents.intent.domain.prompt_builder import (
    build_intent_extraction_system_prompt,
    build_search_extraction_system_prompt,
)
from src.agents.intent.interface.prompt_renderers import (
    build_intent_extraction_chat_prompt,
    build_search_extraction_chat_prompt,
)
from src.infrastructure.llm.provider import get_llm
from src.shared.kernel.tools.logger import get_logger, log_event

# Load environment variables
load_dotenv(find_dotenv())

logger = get_logger(__name__)


class _IntentExtractionLike(Protocol):
    company_name: str | None
    ticker: str | None
    is_valuation_request: bool
    reasoning: str | None

    def model_dump(self, *, mode: str = "python") -> dict[str, object]: ...


class _SearchCandidateLike(Protocol):
    symbol: str
    name: str
    exchange: str | None
    type: str | None
    confidence: float


class _SearchExtractionLike(Protocol):
    candidates: list[_SearchCandidateLike]


def _heuristic_extract(
    query: str, *, intent_model_factory: Callable[..., _IntentExtractionLike]
) -> _IntentExtractionLike:
    heuristic = heuristic_extract_intent(query)
    return intent_model_factory(
        company_name=heuristic.company_name,
        ticker=heuristic.ticker,
        is_valuation_request=heuristic.is_valuation_request,
        reasoning=heuristic.reasoning,
    )


def deduplicate_candidates(candidates: list[TickerCandidate]) -> list[TickerCandidate]:
    """
    De-duplicate ticker candidates that are likely the same security (e.g., BRK.B vs BRK-B).
    """
    seen_normalized: dict[str, TickerCandidate] = {}
    unique_candidates: list[TickerCandidate] = []

    for candidate in candidates:
        norm_symbol = re.sub(r"[\.\-]", "", candidate.symbol.upper())

        if norm_symbol not in seen_normalized:
            seen_normalized[norm_symbol] = candidate
            unique_candidates.append(candidate)
        else:
            if candidate.confidence > seen_normalized[norm_symbol].confidence:
                idx = unique_candidates.index(seen_normalized[norm_symbol])
                unique_candidates[idx] = candidate
                seen_normalized[norm_symbol] = candidate

    return unique_candidates


def extract_candidates_from_search(
    query: str,
    search_results: str,
    *,
    search_extraction_model_type: type[object],
    to_ticker_candidate_fn: Callable[[object], TickerCandidate],
) -> list[TickerCandidate]:
    """
    Extract potential ticker symbols and company names from search results using LLM.
    """
    try:
        llm = get_llm(timeout=30)

        prompt = build_search_extraction_chat_prompt(
            system_prompt=build_search_extraction_system_prompt(),
        )

        chain = prompt | llm.with_structured_output(search_extraction_model_type)
        response = chain.invoke({"query": query, "search_results": search_results})
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
            fields={"exception": str(exc)},
        )
        return []


def extract_intent(
    query: str, *, intent_model_type: type[_IntentExtractionLike]
) -> _IntentExtractionLike:
    """
    Extract intent from user query using LLM with heuristic resilience path.
    """
    try:
        llm = get_llm(timeout=30)

        prompt = build_intent_extraction_chat_prompt(
            system_prompt=build_intent_extraction_system_prompt(),
        )

        chain = prompt | llm.with_structured_output(intent_model_type)
        response = chain.invoke({"query": query})
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
            fields={"exception": str(exc)},
        )
        return _heuristic_extract(query, intent_model_factory=intent_model_type)
