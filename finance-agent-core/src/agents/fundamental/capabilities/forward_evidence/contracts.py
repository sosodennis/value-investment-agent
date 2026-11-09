from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ForwardEvidenceResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    opt_in: Literal[True]
    ticker: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9.-]+$")
    issuer_id: str = Field(min_length=1, max_length=256)
    model_id: Literal["fcff_dcf", "transition_fcff_dcf"]
    assumption_path: str = Field(min_length=1, max_length=256)
    question: str = Field(min_length=8, max_length=512)
    valuation_timestamp: datetime
    automatic_preparation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class ForwardEvidenceClaimDraft(BaseModel):
    """LLM output: only a candidate; the service remains the quality gate."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    metric: Literal[
        "revenue_growth", "operating_margin", "reinvestment_rate", "debt_term"
    ]
    assumption_path: str | None = Field(default=None, max_length=256)
    value: Decimal
    unit: Literal["ratio", "currency", "days", "text"]
    fiscal_period: str = Field(min_length=2, max_length=32)
    period_type: Literal["annual", "quarterly"]
    period_end: str = Field(min_length=10, max_length=32)
    source_url: str = Field(min_length=1, max_length=2048)
    source_passage: str = Field(min_length=20, max_length=8192)
    source_type: Literal[
        "issuer_guidance", "analyst_estimate", "debt_terms", "search_discovery"
    ]
    license_status: Literal["approved", "unknown", "rejected"] = "unknown"
    license_reference: str | None = Field(default=None, max_length=2048)


class ForwardEvidenceExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    claims: tuple[ForwardEvidenceClaimDraft, ...] = Field(
        default_factory=tuple, max_length=8
    )
