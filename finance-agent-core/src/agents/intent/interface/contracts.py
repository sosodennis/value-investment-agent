from __future__ import annotations

from pydantic import BaseModel, Field


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

    candidates: list[TickerCandidateModel] = Field(
        default_factory=list,
        description="List of potential stock tickers found in search results.",
    )
    reasoning: str | None = Field(
        None, description="Brief reasoning for why these candidates were chosen."
    )


class TickerCandidateModel(BaseModel):
    symbol: str = Field(..., description="Stock ticker symbol")
    name: str = Field(..., description="Company name")
    exchange: str | None = Field(None, description="Exchange code")
    type: str | None = Field(None, description="Security type (stock, ETF, etc.)")
    confidence: float = Field(1.0, description="Match confidence score (0-1)")
