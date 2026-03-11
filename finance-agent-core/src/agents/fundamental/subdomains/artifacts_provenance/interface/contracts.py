from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from src.agents.fundamental.subdomains.financial_statements.interface.contracts import (
    FinancialReportModel,
)
from src.agents.fundamental.subdomains.financial_statements.interface.types import (
    FundamentalText,
)
from src.agents.fundamental.subdomains.forward_signals.interface.contracts import (
    ForwardSignalPayload,
)
from src.interface.artifacts.artifact_model_shared import (
    as_mapping,
    to_optional_string,
    to_string,
    validate_and_dump,
)
from src.shared.kernel.types import JSONObject


class FundamentalArtifactModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: FundamentalText
    model_type: FundamentalText
    company_name: FundamentalText
    sector: FundamentalText
    industry: FundamentalText
    reasoning: FundamentalText
    financial_reports: list[FinancialReportModel]
    forward_signals: list[ForwardSignalPayload] | None = None
    valuation_diagnostics: dict[str, object] | None = None
    status: Literal["done"]

    @model_validator(mode="before")
    @classmethod
    def _normalize_root(cls, data: object) -> object:
        mapping = dict(as_mapping(data, "fundamental artifact"))
        ticker = to_string(mapping.get("ticker"), "fundamental artifact.ticker")
        status = to_string(mapping.get("status"), "fundamental artifact.status")
        if status != "done":
            raise TypeError("fundamental artifact.status must be 'done'")
        mapping["ticker"] = ticker
        mapping["company_name"] = (
            to_optional_string(
                mapping.get("company_name"), "fundamental artifact.company_name"
            )
            or ticker
        )
        mapping["sector"] = (
            to_optional_string(mapping.get("sector"), "fundamental artifact.sector")
            or "Unknown"
        )
        mapping["industry"] = (
            to_optional_string(mapping.get("industry"), "fundamental artifact.industry")
            or "Unknown"
        )
        mapping["reasoning"] = (
            to_optional_string(
                mapping.get("reasoning"), "fundamental artifact.reasoning"
            )
            or ""
        )
        mapping["status"] = "done"
        return mapping


def parse_fundamental_artifact_model(value: object) -> JSONObject:
    return validate_and_dump(
        FundamentalArtifactModel, value, "fundamental artifact", exclude_none=False
    )


__all__ = ["FundamentalArtifactModel", "parse_fundamental_artifact_model"]
