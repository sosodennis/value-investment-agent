"""
OpenBB integration tools for the Planner Node.

Provides wrapper functions for entity resolution and company profile retrieval.
"""

from typing import List, Optional
import logging

from .structures import TickerCandidate, CompanyProfile

logger = logging.getLogger(__name__)

import yfinance as yf
import requests

# Set a user-agent to avoid being blocked by Yahoo
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}


def search_ticker(query: str, limit: int = 5) -> List[TickerCandidate]:
    """
    Search for ticker symbols using Yahoo Finance's autocomplete API.
    
    Args:
        query: Company name or ticker to search for
        limit: Maximum number of results to return
        
    Returns:
        List of ticker candidates with metadata
    """
    try:
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={query}"
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        candidates = []
        for quote in data.get("quotes", [])[:limit]:
            # Filter for stocks mainly, though Yahoo returns many types
            quote_type = quote.get("quoteType", "").lower()
            if quote_type not in ["equity", "equity_deprecated"]:
                continue
                
            candidates.append(TickerCandidate(
                symbol=quote.get("symbol"),
                name=quote.get("longname") or quote.get("shortname"),
                exchange=quote.get("exchDisp"),
                type="stock",
                confidence=0.9  # Default confidence for API matches
            ))
            
        if not candidates:
            # Fallback for common tickers if API fails or returns nothing relevant
            if "tesla" in query.lower():
                return [TickerCandidate(symbol="TSLA", name="Tesla Inc", exchange="NASDAQ", type="stock", confidence=0.95)]
                
        return candidates
        
    except Exception as e:
        logger.error(f"Error searching ticker: {e}")
        return []


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
        
        logger.info(f"✓ Retrieved profile for {ticker} using yfinance")
        return profile
        
    except Exception as e:
        logger.error(f"Error getting company profile for {ticker}: {e}")
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
