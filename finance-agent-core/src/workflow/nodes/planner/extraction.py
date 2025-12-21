"""
Extraction logic for the Planner Node.
Uses LLM to extract intent (Company, Model Preference) from user query.
"""

import os
import re
from typing import Optional, List
from pydantic import BaseModel, Field
from dotenv import load_dotenv, find_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from .structures import ValuationModel, TickerCandidate

# Load environment variables
load_dotenv(find_dotenv())

class IntentExtraction(BaseModel):
    """Extracted intent from user query."""
    company_name: Optional[str] = Field(None, description="The name of the company or ticker mentioned by the user.")
    ticker: Optional[str] = Field(None, description="The stock ticker if explicitly mentioned.")
    model_preference: Optional[ValuationModel] = Field(None, description="Specific valuation model requested by the user, if any.")
    is_valuation_request: bool = Field(..., description="Whether the user is asking for a financial valuation.")
    reasoning: str = Field(..., description="Brief reasoning for the extraction.")

class SearchExtraction(BaseModel):
    """Extracted ticker candidates from web search."""
    candidates: List[TickerCandidate] = Field(default_factory=list, description="List of potential stock tickers found in search results.")
    reasoning: str = Field(..., description="Brief reasoning for why these candidates were chosen.")

def _heuristic_extract(query: str) -> IntentExtraction:
    """
    Fallback parser for when LLM is unavailable.
    Simple keyword matching for major stocks and models.
    """
    query_lower = query.lower()
    
    # 1. Look for obvious tickers (all caps, 1-5 chars)
    tickers = re.findall(r'\b[A-Z]{1,5}\b', query)
    ticker = tickers[0] if tickers else None
    
    # 2. Look for model keywords
    model_pref = None
    if "ddm" in query_lower:
        model_pref = ValuationModel.DDM
    elif "reit" in query_lower or "ffo" in query_lower:
        model_pref = ValuationModel.FFO
    elif "growth" in query_lower:
        model_pref = ValuationModel.DCF_GROWTH
    elif "dcf" in query_lower:
        model_pref = ValuationModel.DCF_STANDARD
        
    # 3. Guess company name if no ticker
    company_name = ticker
    if not company_name:
        # Filter out common valuation stop words
        stop_words = {"valuation", "valuate", "value", "price", "stock", "analysis", "report", "for", "of", "the", "a", "an"}
        words = query.split()
        
        # Filter words that are not stop words (case-insensitive)
        potential_names = [w for w in words if w.lower() not in stop_words and len(w) > 1]
        
        if potential_names:
            company_name = potential_names[-1] # Take the last meaningful word
        elif words:
            company_name = words[-1] # Fallback to last word if everything else fails

    return IntentExtraction(
        company_name=company_name,
        ticker=ticker,
        model_preference=model_pref,
        is_valuation_request="val" in query_lower or "price" in query_lower or ticker is not None,
        reasoning="Fallback heuristic used due to API error."
    )

def deduplicate_candidates(candidates: List[TickerCandidate]) -> List[TickerCandidate]:
    """
    De-duplicate ticker candidates that are likely the same security (e.g., BRK.B vs BRK-B).
    """
    seen_normalized = {}
    unique_candidates = []
    
    for candidate in candidates:
        # Normalize: uppercase, remove common delimiters for sharing classes
        norm_symbol = re.sub(r'[\.\-]', '', candidate.symbol.upper())
        
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

def extract_candidates_from_search(query: str, search_results: str) -> List[TickerCandidate]:
    """
    Extract potential ticker symbols and company names from search results using LLM.
    """
    try:
        llm = ChatOpenAI(
            model="openai/gpt-oss-20b:free",
            temperature=0,
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY")
        )
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a financial data extractor. Analyze the search results for a user query about a stock and extract ALL potential ticker symbols and their corresponding company names. "
                       "Assign a confidence score (0-1) based on how likely the ticker matches the user's intent. "
                       "Note: Use the standard ticker format (e.g., BRK-B or BRK.B). If multiple formats are found, return the most common one. "
                       "Return a list of TickerCandidate objects."),
            ("user", "User Query: {query}\n\nSearch Results: {search_results}")
        ])
        
        chain = prompt | llm.with_structured_output(SearchExtraction)
        response = chain.invoke({"query": query, "search_results": search_results})
        
        return response.candidates
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"LLM Search Extraction failed: {e}. Returning empty list.")
        return []

def extract_intent(query: str) -> IntentExtraction:
    """
    Extract intent from user query using LLM with heuristic fallback.
    """
    try:
        llm = ChatOpenAI(
            model="openai/gpt-oss-20b:free",
            temperature=0,
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY")
        )
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a financial analyst assistant. Extract the company name, ticker, and any specific valuation model preference from the user's request. "
                       "Recognized models: {models}."),
            ("user", "{query}")
        ])
        
        model_list = [m.value for m in ValuationModel]
        chain = prompt | llm.with_structured_output(IntentExtraction)
        response = chain.invoke({"query": query, "models": model_list})
        return response
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"LLM Extraction failed (likely quota/rate limit): {e}. Using fallback.")
        return _heuristic_extract(query)
