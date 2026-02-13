from __future__ import annotations

from pydantic import BaseModel, Field

from src.agents.intent.domain.models import TickerCandidate


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

    candidates: list[TickerCandidate] = Field(
        default_factory=list,
        description="List of potential stock tickers found in search results.",
    )
    reasoning: str | None = Field(
        None, description="Brief reasoning for why these candidates were chosen."
    )
