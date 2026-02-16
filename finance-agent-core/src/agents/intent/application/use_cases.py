"""
Extraction logic for the Intent agent.
Uses LLM to extract intent (Company, Model Preference) from user query.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Protocol

from dotenv import find_dotenv, load_dotenv
from langchain_core.prompts import ChatPromptTemplate

from src.agents.intent.domain.extraction_policies import heuristic_extract_intent
from src.agents.intent.domain.models import TickerCandidate
from src.infrastructure.llm.provider import get_llm
from src.shared.kernel.tools.logger import get_logger

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

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """You are a strict financial entity extractor.
            Your goal is to identify the ticker symbol for the SPECIFIC company mentioned by the user.

            RULES:
            1. ONLY extract the ticker that belongs to the company '{query}'.
            2. IGNORE tickers of competitors, partners, or other companies mentioned in the text (e.g., if searching for 'Tesla', ignore 'AAPL', 'GOOGL', 'AMZN' even if they appear in the text).
            3. If the text mentions "competitors include...", do NOT extract those tickers.
            4. Assign a confidence score (0-1). If the ticker explicitly matches the company name in the text (e.g., "Tesla (TSLA)"), assign 1.0.
            5. If no ticker matches the specific company '{query}', return an empty list.
            """,
                ),
                ("user", "User Query: {query}\n\nSearch Results: {search_results}"),
            ]
        )

        chain = prompt | llm.with_structured_output(search_extraction_model_type)
        response = chain.invoke({"query": query, "search_results": search_results})
        candidates_raw = getattr(response, "candidates", None)
        if not isinstance(candidates_raw, list):
            raise TypeError("search extraction output shape is invalid")
        return [to_ticker_candidate_fn(candidate) for candidate in candidates_raw]
    except Exception as exc:
        logger.warning(f"LLM Search Extraction failed: {exc}. Returning empty list.")
        return []


def extract_intent(
    query: str, *, intent_model_type: type[_IntentExtractionLike]
) -> _IntentExtractionLike:
    """
    Extract intent from user query using LLM with heuristic resilience path.
    """
    try:
        llm = get_llm(timeout=30)

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """You are a precise financial entity extractor.
Your goal is to extract exactly what the user said, NOT to guess what they meant.

RULES:
1. **Company Name**: Extract the entity name mentioned (e.g., "Google", "Tesla").
2. **Ticker**: ONLY extract a ticker if the user EXPLICITLY typed a ticker symbol (e.g., "GOOG", "$TSLA", "stock symbol for Apple").
3. **CRITICAL**: If the user says "Google", do NOT infer "GOOGL". Leave the ticker field empty.
4. **CRITICAL**: If the user says "Alphabet", do NOT infer "GOOG". Leave the ticker field empty.
5. **CRITICAL**: Set `is_valuation_request` to true if the user wants to valuate, price, or analyze a company's financial value.

Return the IntentExtraction object.
""",
                ),
                ("user", "{query}"),
            ]
        )

        chain = prompt | llm.with_structured_output(intent_model_type)
        response = chain.invoke({"query": query})
        model_dump = getattr(response, "model_dump", None)
        if not callable(model_dump):
            raise TypeError("intent extraction output shape is invalid")
        dumped = model_dump(mode="json")
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
        logger.warning(
            "LLM Extraction failed: %s. Using heuristic resilience path.", exc
        )
        return _heuristic_extract(query, intent_model_factory=intent_model_type)
