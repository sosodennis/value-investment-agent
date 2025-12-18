"""
Model selection logic for the Planner Node.

Implements GICS-based rules to automatically select the appropriate valuation model.
"""

import logging
from typing import Optional

from .structures import CompanyProfile, ValuationModel

logger = logging.getLogger(__name__)


def select_valuation_model(profile: CompanyProfile) -> tuple[ValuationModel, str]:
    """
    Select the appropriate valuation model based on company characteristics.
    
    Implements the logic from research-planner-0.md section 6.1:
    - Banks -> DDM (Dividend Discount Model)
    - REITs -> FFO (Funds From Operations)
    - High-growth tech (unprofitable) -> EV/Revenue
    - Mature tech/industrials -> DCF
    
    Args:
        profile: Company profile with sector and industry information
        
    Returns:
        Tuple of (selected_model, reasoning)
        
    Example:
        >>> profile = CompanyProfile(ticker="JPM", sector="Financial Services", industry="Banks")
        >>> model, reason = select_valuation_model(profile)
        >>> model
        ValuationModel.DDM
    """
    sector = (profile.sector or "").lower()
    industry = (profile.industry or "").lower()
    
    # Rule 1: Banks and Financial Institutions -> DDM
    # Reasoning: Banks' debt is operational, not financing. P/B and DDM are appropriate.
    if "financial" in sector or "bank" in industry:
        if "bank" in industry or "banking" in industry:
            return (
                ValuationModel.DDM,
                "Banking sector: Asset-liability driven business. Using Dividend Discount Model (DDM) "
                "as debt is operational capital, not financing cost. P/E and DDM are standard for banks."
            )
    
    # Rule 2: REITs -> FFO
    # Reasoning: Depreciation distorts net income for real estate
    if "real estate" in sector or "reit" in industry:
        return (
            ValuationModel.FFO,
            "Real Estate Investment Trust (REIT): Accounting depreciation masks property appreciation. "
            "Using Funds From Operations (FFO) model which adjusts for non-cash depreciation."
        )
    
    # Rule 3: Utilities -> DDM
    # Reasoning: Bond-like characteristics, stable dividends
    if "utilities" in sector or "utility" in industry:
        return (
            ValuationModel.DDM,
            "Utilities sector: Bond-like characteristics with limited growth but stable dividends. "
            "Using Dividend Discount Model (DDM) as investors focus on dividend yield."
        )
    
    # Rule 4: Technology sector - need to check profitability
    if "technology" in sector or "information technology" in sector:
        # If unprofitable or high-growth SaaS
        if profile.is_profitable is False or "software" in industry or "saas" in industry.lower():
            return (
                ValuationModel.DCF_GROWTH,
                "High-growth technology/SaaS company: May have negative earnings or high reinvestment. "
                "Using growth-adjusted DCF focusing on revenue growth and long-term free cash flow potential."
            )
        else:
            # Profitable tech company
            return (
                ValuationModel.DCF_STANDARD,
                "Mature technology company with positive cash flows. "
                "Using standard Discounted Cash Flow (DCF) model based on Free Cash Flow to Firm (FCFF)."
            )
    
    # Rule 5: Consumer Cyclical (e.g., Auto, Retail)
    if "consumer" in sector or "cyclical" in sector:
        # Special case: Auto manufacturers often have complex financing arms
        if "auto" in industry or "vehicle" in industry:
            return (
                ValuationModel.DCF_GROWTH,
                "Automotive/EV manufacturer: Capital-intensive with potential high growth (especially EVs). "
                "Using growth-adjusted DCF to capture future market expansion and technology transition."
            )
        else:
            return (
                ValuationModel.DCF_STANDARD,
                "Consumer sector company with established business model. "
                "Using standard DCF based on stable cash flow generation."
            )
    
    # Rule 6: Industrials, Materials, Energy -> Standard DCF
    if any(x in sector for x in ["industrial", "material", "energy"]):
        return (
            ValuationModel.DCF_STANDARD,
            f"{sector.title()} sector: Mature business with predictable cash flows. "
            "Using standard Discounted Cash Flow (DCF) model."
        )
    
    # Default: Standard DCF for unknown sectors
    logger.warning(f"Unknown sector/industry for {profile.ticker}: {sector}/{industry}. Using default DCF.")
    return (
        ValuationModel.DCF_STANDARD,
        f"Default valuation approach for {sector or 'unknown'} sector. "
        "Using standard Discounted Cash Flow (DCF) model. "
        "Consider manual review for sector-specific adjustments."
    )


def should_request_clarification(candidates: list, confidence_threshold: float = 0.85) -> bool:
    """
    Determine if human clarification is needed for ticker resolution.
    
    Args:
        candidates: List of ticker candidates
        confidence_threshold: Minimum confidence to auto-select
        
    Returns:
        True if clarification is needed
    """
    if not candidates:
        return True  # No matches found
    
    if len(candidates) == 1 and candidates[0].confidence >= confidence_threshold:
        return False  # Single high-confidence match
    
    if len(candidates) > 1:
        # Check if top two candidates are very close in confidence
        if len(candidates) >= 2:
            top_conf = candidates[0].confidence
            second_conf = candidates[1].confidence
            # Relaxed threshold to catch cases like GOOG (0.9) vs GOOGL (1.0)
            # where the difference is exactly 0.1
            if abs(top_conf - second_conf) <= 0.15:  # Ambiguous
                return True
        # If we have multiple candidates but they're not close in confidence,
        # still ask for clarification to be safe
        return True
    
    return False
