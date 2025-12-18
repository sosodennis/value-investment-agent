"""
Planner Node - Entity Resolution and Valuation Model Selection.

This node:
1. Resolves user queries to stock tickers using OpenBB
2. Retrieves company profiles
3. Selects appropriate valuation models based on GICS sectors
4. Supports Human-in-the-Loop for ambiguous cases
"""

import logging
from typing import TYPE_CHECKING, Optional

from .tools import search_ticker, get_company_profile
from .logic import select_valuation_model, should_request_clarification
from .structures import ValuationModel, PlannerOutput

if TYPE_CHECKING:
    from ...graph import AgentState

logger = logging.getLogger(__name__)


def extract_query_from_state(state: "AgentState") -> str:
    """
    Extract the user query from state.
    
    For now, we assume ticker is provided directly.
    In future, this would parse natural language like "Value Tesla".
    """
    # If ticker is already in state, use it as query
    if "ticker" in state and state["ticker"]:
        return state["ticker"]
    
    # Otherwise, look for a user_query field
    if "user_query" in state:
        return state["user_query"]
    
    raise ValueError("No ticker or user_query found in state")


def planner_node(state: "AgentState") -> dict:
    """
    Main Planner Node - Orchestrates entity resolution and model selection.
    
    Workflow:
    1. Extract query from state
    2. Search for ticker using OpenBB
    3. Get company profile
    4. Select valuation model based on GICS sector
    5. Return updated state
    
    Args:
        state: Current agent state
        
    Returns:
        Updated state with model_type, company info, and reasoning
        
    Raises:
        ValueError: If ticker cannot be resolved
    """
    logger.info("=== Planner Node Started ===")
    
    try:
        # Step 1: Extract query
        query = extract_query_from_state(state)
        logger.info(f"Processing query: {query}")
        
        # Step 2: Resolve ticker
        # For MVP, if query looks like a ticker (all caps, short), use directly
        # Otherwise, search for it
        ticker = query.upper()
        
        if len(ticker) > 5 or not ticker.isalpha():
            # Likely a company name, search for it
            logger.info(f"Searching for ticker: {query}")
            candidates = search_ticker(query)
            
            if not candidates:
                raise ValueError(f"No ticker found for query: {query}")
            
            # Check if clarification needed
            if should_request_clarification(candidates):
                # TODO: Implement HITL interruption here
                # For now, take the top candidate
                logger.warning(f"Ambiguous query, using top candidate: {candidates[0].symbol}")
            
            ticker = candidates[0].symbol
            company_name = candidates[0].name
        else:
            # Assume it's already a ticker
            company_name = ticker  # Will be updated from profile
        
        logger.info(f"Resolved ticker: {ticker}")
        
        # Step 3: Get company profile
        profile = get_company_profile(ticker)
        
        if not profile:
            raise ValueError(f"Could not retrieve profile for ticker: {ticker}")
        
        company_name = profile.name
        logger.info(f"Retrieved profile for {company_name} ({ticker})")
        logger.info(f"Sector: {profile.sector}, Industry: {profile.industry}")
        
        # Step 4: Select valuation model
        model, reasoning = select_valuation_model(profile)
        logger.info(f"Selected model: {model.value}")
        logger.info(f"Reasoning: {reasoning}")
        
        # Step 5: Update state
        # Map our ValuationModel enum to the existing state's model_type format
        model_type_map = {
            ValuationModel.DCF_GROWTH: "saas",  # Map to existing 'saas' type
            ValuationModel.DCF_STANDARD: "saas",  # Also use saas for standard DCF
            ValuationModel.DDM: "bank",  # Map to existing 'bank' type
            ValuationModel.FFO: "saas",  # Use saas model structure for now
            ValuationModel.EV_REVENUE: "saas",
            ValuationModel.EV_EBITDA: "saas",
        }
        
        model_type = model_type_map.get(model, "saas")
        
        print(f"\n{'='*60}")
        print(f"PLANNER DECISION")
        print(f"{'='*60}")
        print(f"Company: {company_name} ({ticker})")
        print(f"Sector: {profile.sector or 'Unknown'}")
        print(f"Industry: {profile.industry or 'Unknown'}")
        print(f"Selected Model: {model.value}")
        print(f"Reasoning: {reasoning}")
        print(f"{'='*60}\n")
        
        return {
            "ticker": ticker,
            "model_type": model_type,
            # Store additional metadata for downstream nodes
            "planner_output": {
                "company_name": company_name,
                "sector": profile.sector,
                "industry": profile.industry,
                "selected_model": model.value,
                "reasoning": reasoning
            }
        }
        
    except Exception as e:
        logger.error(f"Planner node failed: {e}")
        # For now, fallback to basic behavior
        ticker = state.get("ticker", "UNKNOWN")
        print(f"\n⚠️  Planner Error: {e}")
        print(f"Falling back to default model for {ticker}\n")
        
        return {
            "ticker": ticker,
            "model_type": state.get("model_type", "saas"),
            "planner_output": {
                "error": str(e),
                "fallback": True
            }
        }
