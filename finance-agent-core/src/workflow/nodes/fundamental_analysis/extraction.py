"""
Extraction logic for the Planner Node.
Uses LLM to extract intent (Company, Model Preference) from user query.
"""

import os
import re

from dotenv import find_dotenv, load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from .structures import TickerCandidate

# Load environment variables
load_dotenv(find_dotenv())


class IntentExtraction(BaseModel):
    """Extracted intent from user query."""

    company_name: str | None = Field(
        None, description="The name of the company or ticker mentioned by the user."
    )
    ticker: str | None = Field(
        None, description="The stock ticker if explicitly mentioned."
    )
    is_valuation_request: bool = Field(
        True,
        description="Whether the user is asking for a financial valuation (default: True).",
    )
    reasoning: str | None = Field(
        None, description="Brief reasoning for the extraction."
    )


class SearchExtraction(BaseModel):
    """Extracted ticker candidates from web search."""

    candidates: list[TickerCandidate] = Field(
        default_factory=list,
        description="List of potential stock tickers found in search results.",
    )
    reasoning: str | None = Field(
        None, description="Brief reasoning for why these candidates were chosen."
    )


def _heuristic_extract(query: str) -> IntentExtraction:
    """
    Fallback parser for when LLM is unavailable.
    Simple keyword matching for major stocks.
    """
    query_lower = query.lower()

    # 1. Look for obvious tickers (all caps, 1-5 chars)
    tickers = re.findall(r"\b[A-Z]{1,5}\b", query)
    ticker = tickers[0] if tickers else None

    # 2. Extract company name if no ticker
    company_name = ticker
    if not company_name:
        # Filter out common valuation stop words
        stop_words = {
            "valuation",
            "valuate",
            "value",
            "price",
            "stock",
            "analysis",
            "report",
            "for",
            "of",
            "the",
            "a",
            "an",
        }
        words = query.split()

        # Filter words that are not stop words (case-insensitive)
        potential_names = [
            w for w in words if w.lower() not in stop_words and len(w) > 1
        ]

        if potential_names:
            company_name = potential_names[-1]  # Take the last meaningful word
        elif words:
            company_name = words[-1]  # Fallback to last word if everything else fails

    return IntentExtraction(
        company_name=company_name,
        ticker=ticker,
        is_valuation_request="val" in query_lower
        or "price" in query_lower
        or ticker is not None,
        reasoning="Fallback heuristic used due to API error.",
    )


def deduplicate_candidates(candidates: list[TickerCandidate]) -> list[TickerCandidate]:
    """
    De-duplicate ticker candidates that are likely the same security (e.g., BRK.B vs BRK-B).
    """
    seen_normalized = {}
    unique_candidates = []

    for candidate in candidates:
        # Normalize: uppercase, remove common delimiters for sharing classes
        norm_symbol = re.sub(r"[\.\-]", "", candidate.symbol.upper())

        if norm_symbol not in seen_normalized:
            seen_normalized[norm_symbol] = candidate
            unique_candidates.append(candidate)
        else:
            # If current candidate has higher confidence, replace the existing one
            if candidate.confidence > seen_normalized[norm_symbol].confidence:
                # Update in the list as well
                idx = unique_candidates.index(seen_normalized[norm_symbol])
                unique_candidates[idx] = candidate
                seen_normalized[norm_symbol] = candidate

    return unique_candidates


def extract_candidates_from_search(
    query: str, search_results: str
) -> list[TickerCandidate]:
    """
    Extract potential ticker symbols and company names from search results using LLM.
    """
    try:
        llm = ChatOpenAI(
            model="z-ai/glm-4.5-air:free",
            temperature=0,
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
            timeout=30,
            max_retries=2,
        )

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

        chain = prompt | llm.with_structured_output(SearchExtraction)
        response = chain.invoke({"query": query, "search_results": search_results})

        return response.candidates
    except Exception as e:
        from src.utils.logger import get_logger

        logger = get_logger(__name__)
        logger.warning(f"LLM Search Extraction failed: {e}. Returning empty list.")
        return []


def extract_intent(query: str) -> IntentExtraction:
    """
    Extract intent from user query using LLM with heuristic fallback.
    """
    try:
        llm = ChatOpenAI(
            model="z-ai/glm-4.5-air:free",
            temperature=0,
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
            timeout=30,
            max_retries=2,
        )

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

        chain = prompt | llm.with_structured_output(IntentExtraction)
        response = chain.invoke({"query": query})
        return response
    except Exception as e:
        from src.utils.logger import get_logger

        logger = get_logger(__name__)
        logger.warning(f"LLM Extraction failed: {e}. Using fallback.")
        return _heuristic_extract(query)
