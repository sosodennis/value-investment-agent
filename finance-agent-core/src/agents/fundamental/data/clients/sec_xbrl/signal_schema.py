from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ForwardSignalEvidencePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text_snippet: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    doc_type: str | None = None
    period: str | None = None
    filing_date: str | None = None
    accession_number: str | None = None
    focus_strategy: str | None = None
    rule: str | None = None
    value_basis_points: float | None = None


class ForwardSignalPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_id: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    direction: Literal["up", "down", "neutral"]
    value: float
    unit: Literal["basis_points", "ratio"]
    confidence: float = Field(ge=0.0, le=1.0)
    as_of: str
    evidence: list[ForwardSignalEvidencePayload]
    median_filing_age_days: int | None = None
