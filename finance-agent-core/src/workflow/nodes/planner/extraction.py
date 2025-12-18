"""
Extraction logic for the Planner Node.
Uses LLM to extract intent (Company, Model Preference) from user query.
"""

from typing import Optional, List
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from .structures import ValuationModel

class IntentExtraction(BaseModel):
    """Extracted intent from user query."""
    company_name: Optional[str] = Field(None, description="The name of the company or ticker mentioned by the user.")
    ticker: Optional[str] = Field(None, description="The stock ticker if explicitly mentioned.")
    model_preference: Optional[ValuationModel] = Field(None, description="Specific valuation model requested by the user, if any.")
    is_valuation_request: bool = Field(..., description="Whether the user is asking for a financial valuation.")
    reasoning: str = Field(..., description="Brief reasoning for the extraction.")

def _heuristic_extract(query: str) -> IntentExtraction:
    """
    Fallback parser for when LLM is unavailable.
    Simple keyword matching for major stocks and models.
    """
    query_lower = query.lower()
    
    # 1. Look for obvious tickers (all caps, 1-5 chars)
    import re
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
        # Very crude: take the last word if it's not a model
        words = query.split()
        if words:
            company_name = words[-1]

    return IntentExtraction(
        company_name=company_name,
        ticker=ticker,
        model_preference=model_pref,
        is_valuation_request="val" in query_lower or "price" in query_lower or ticker is not None,
        reasoning="Fallback heuristic used due to API error."
    )

def extract_intent(query: str) -> IntentExtraction:
    """
    Extract intent from user query using LLM with heuristic fallback.
    """
    try:
        llm = ChatOpenAI(model="gpt-4o", temperature=0)
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a financial analyst assistant. Extract the company name, ticker, and any specific valuation model preference from the user's request. "
                       "Recognized models: {models}."),
            ("user", "{query}")
        ])
        
        model_list = [m.value for m in ValuationModel]
        chain = prompt | llm.with_structured_output(IntentExtraction)
        
        return chain.invoke({"query": query, "models": model_list})
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"LLM Extraction failed (likely quota/rate limit): {e}. Using fallback.")
        return _heuristic_extract(query)
