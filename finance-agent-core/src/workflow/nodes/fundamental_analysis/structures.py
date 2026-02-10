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
    RESIDUAL_INCOME = "residual_income"  # Residual Income Model
    EVA = "eva"  # Economic Value Added


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
