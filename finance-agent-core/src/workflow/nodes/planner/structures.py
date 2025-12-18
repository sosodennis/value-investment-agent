"""
Data structures for the Planner Node.

Defines the input, state, and output schemas for the Planner's operation.
"""

from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field


class ValuationModel(str, Enum):
    """Available valuation models based on industry characteristics."""
    DCF_GROWTH = "dcf_growth"  # High-growth tech/SaaS (FCFF/DCF)
    DCF_STANDARD = "dcf_standard"  # Mature industrials/consumer
    DDM = "ddm"  # Banks, utilities (Dividend Discount Model)
    FFO = "ffo"  # REITs (Funds From Operations)
    EV_REVENUE = "ev_revenue"  # Pre-profit tech companies
    EV_EBITDA = "ev_ebitda"  # General purpose multiple


class TickerCandidate(BaseModel):
    """A potential ticker match from search."""
    symbol: str = Field(..., description="Stock ticker symbol")
    name: str = Field(..., description="Company name")
    exchange: Optional[str] = Field(None, description="Exchange code")
    type: Optional[str] = Field(None, description="Security type (stock, ETF, etc.)")
    confidence: float = Field(1.0, description="Match confidence score (0-1)")


class CompanyProfile(BaseModel):
    """Company profile information for model selection."""
    ticker: str
    name: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    description: Optional[str] = None
    market_cap: Optional[float] = None
    is_profitable: Optional[bool] = None


class PlannerInput(BaseModel):
    """Input to the Planner Node."""
    user_query: str = Field(..., description="Natural language request (e.g., 'Value Tesla')")


class PlannerState(BaseModel):
    """Internal state during planning process."""
    user_query: str
    ticker_candidates: List[TickerCandidate] = Field(default_factory=list)
    selected_ticker: Optional[str] = None
    company_profile: Optional[CompanyProfile] = None
    selected_model: Optional[ValuationModel] = None
    needs_clarification: bool = False
    confidence_score: float = 0.0


class PlannerOutput(BaseModel):
    """Output from the Planner Node - instructions for Executor."""
    ticker: str = Field(..., description="Confirmed stock ticker")
    model_type: ValuationModel = Field(..., description="Selected valuation model")
    company_name: str = Field(..., description="Company name")
    sector: Optional[str] = Field(None, description="GICS sector")
    industry: Optional[str] = Field(None, description="GICS industry")
    reasoning: str = Field(..., description="Why this model was selected")
