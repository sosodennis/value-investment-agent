from __future__ import annotations

from pydantic import BaseModel


class CompanyProfile(BaseModel):
    """Company profile information for ticker resolution and model selection."""

    ticker: str
    name: str
    sector: str | None = None
    industry: str | None = None
    description: str | None = None
    market_cap: float | None = None
    is_profitable: bool | None = None
