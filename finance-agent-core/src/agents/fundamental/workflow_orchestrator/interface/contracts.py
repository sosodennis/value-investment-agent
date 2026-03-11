from __future__ import annotations

from typing import Annotated, TypeAlias

from pydantic import BaseModel, BeforeValidator, ConfigDict

from src.interface.artifacts.artifact_model_shared import (
    to_number,
    to_optional_string,
    to_string,
)


def _parse_fundamental_text(value: object) -> str:
    return to_string(value, "fundamental preview text")


FundamentalText: TypeAlias = Annotated[str, BeforeValidator(_parse_fundamental_text)]


def _parse_optional_fundamental_text(value: object) -> str | None:
    return to_optional_string(value, "fundamental preview optional text")


def _parse_optional_fundamental_number(value: object) -> float | None:
    if value is None:
        return None
    return to_number(value, "fundamental preview optional number")


OptionalFundamentalText: TypeAlias = Annotated[
    str | None,
    BeforeValidator(_parse_optional_fundamental_text),
]
OptionalFundamentalNumber: TypeAlias = Annotated[
    float | None,
    BeforeValidator(_parse_optional_fundamental_number),
]


class FundamentalPreviewInputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: FundamentalText
    company_name: FundamentalText
    sector: FundamentalText
    industry: FundamentalText
    status: FundamentalText
    selected_model: OptionalFundamentalText = None
    model_type: OptionalFundamentalText = None
    valuation_summary: OptionalFundamentalText = None
    valuation_score: OptionalFundamentalNumber = None
    assumption_breakdown: dict[str, object] | None = None
    data_freshness: dict[str, object] | None = None
    assumption_risk_level: OptionalFundamentalText = None
    data_quality_flags: list[str] | None = None
    time_alignment_status: OptionalFundamentalText = None
    forward_signal_summary: dict[str, object] | None = None
    forward_signal_risk_level: OptionalFundamentalText = None
    forward_signal_evidence_count: OptionalFundamentalNumber = None


__all__ = ["FundamentalPreviewInputModel"]
