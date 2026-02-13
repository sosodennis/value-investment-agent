from __future__ import annotations

from pydantic import BaseModel, Field


class TickerCandidate(BaseModel):
    """A potential ticker match from search."""

    symbol: str = Field(..., description="Stock ticker symbol")
    name: str = Field(..., description="Company name")
    exchange: str | None = Field(None, description="Exchange code")
    type: str | None = Field(None, description="Security type (stock, ETF, etc.)")
    confidence: float = Field(1.0, description="Match confidence score (0-1)")
