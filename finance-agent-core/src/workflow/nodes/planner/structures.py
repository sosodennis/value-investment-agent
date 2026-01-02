"""
Data structures for the Planner Node.

Defines the input, state, and output schemas for the Planner's operation.
"""

from enum import Enum

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
    exchange: str | None = Field(None, description="Exchange code")
    type: str | None = Field(None, description="Security type (stock, ETF, etc.)")
    confidence: float = Field(1.0, description="Match confidence score (0-1)")


class CompanyProfile(BaseModel):
    """Company profile information for model selection."""

    ticker: str
    name: str
    sector: str | None = None
    industry: str | None = None
    description: str | None = None
    market_cap: float | None = None
    is_profitable: bool | None = None


class PlannerInput(BaseModel):
    """Input to the Planner Node."""

    user_query: str = Field(
        ..., description="Natural language request (e.g., 'Value Tesla')"
    )


class PlannerState(BaseModel):
    """Internal state during planning process."""

    user_query: str
    ticker_candidates: list[TickerCandidate] = Field(default_factory=list)
    selected_ticker: str | None = None
    company_profile: CompanyProfile | None = None
    selected_model: ValuationModel | None = None
    needs_clarification: bool = False
    confidence_score: float = 0.0


class PlannerOutput(BaseModel):
    """Output from the Planner Node - instructions for Executor."""

    ticker: str = Field(..., description="Confirmed stock ticker")
    model_type: ValuationModel = Field(..., description="Selected valuation model")
    company_name: str = Field(..., description="Company name")
    sector: str | None = Field(None, description="GICS sector")
    industry: str | None = Field(None, description="GICS industry")
    reasoning: str = Field(..., description="Why this model was selected")
    financial_reports: list[dict] = Field(
        default_factory=list, description="Financial Health Reports (Multi-year)"
    )
