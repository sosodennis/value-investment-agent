"""
OpenBB and Web Search integration tools for the Planner Node.

Provides wrapper functions for entity resolution, company profile retrieval, and web search.
"""

from typing import List, Optional
import logging

from .structures import TickerCandidate, CompanyProfile

import logging
logger = logging.getLogger(__name__)

import yfinance as yf
from langchain_community.tools import DuckDuckGoSearchRun


def search_ticker(query: str, limit: int = 5) -> List[TickerCandidate]:
    """
    Search for ticker symbols using yfinance.Search.
    """
    # Try yfinance.Search
    try:
        search = yf.Search(query)
        quotes = getattr(search, "quotes", [])
        
        candidates = []
        for quote in quotes[:limit]:
            # Filter for stocks
            quote_type = quote.get("quoteType", "").upper()
            if quote_type not in ["EQUITY", "EQUITY_DEPRECATED"]:
                continue
                
            candidates.append(TickerCandidate(
                symbol=quote.get("symbol"),
                name=quote.get("longname") or quote.get("shortname") or quote.get("symbol"),
                exchange=quote.get("exchDisp"),
                type="stock",
                confidence=1.0 if quote.get("symbol") == query.upper() else 0.9
            ))
            
        if candidates:
            return candidates
            
    except Exception as e:
        logger.error(f"yfinance.Search failed: {e}")

    return []


def web_search(query: str) -> str:
    """
    Perform a web search using DuckDuckGo via LangChain.
    """
    try:
        search = DuckDuckGoSearchRun()
        return search.run(query)
    except Exception as e:
        logger.error(f"Web search failed: {e}")
        return f"Web search currently unavailable. Error: {str(e)}"


def get_company_profile(ticker: str) -> Optional[CompanyProfile]:
    """
    Retrieve company profile using yfinance.
    
    Args:
        ticker: Stock ticker symbol
        
    Returns:
        CompanyProfile with sector, industry, and other metadata
    """
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        
        if not info or 'symbol' not in info:
            logger.warning(f"No profile found for ticker: {ticker}")
            return None
            
        profile = CompanyProfile(
            ticker=ticker,
            name=info.get('longName') or info.get('shortName') or ticker,
            sector=info.get('sector'),
            industry=info.get('industry'),
            description=info.get('longBusinessSummary'),
            market_cap=info.get('marketCap'),
            is_profitable=None  # Placeholder, logic for profitability check remains outside
        )
        
        # logger.info(f"✓ Retrieved profile for {ticker} using yfinance")
        return profile
        
    except Exception as e:
        # logger.error(f"Error getting company profile for {ticker}: {e}")
        return None


def validate_ticker(ticker: str) -> bool:
    """
    Validate that a ticker exists and is tradeable.
    
    Args:
        ticker: Stock ticker symbol
        
    Returns:
        True if ticker is valid
    """
    profile = get_company_profile(ticker)
    return profile is not None
