from __future__ import annotations

from dataclasses import dataclass

from src.shared.kernel.types import JSONObject


@dataclass(frozen=True)
class FundamentalAppContextDTO:
    ticker: str
    status: str
    company_name: str
    sector: str | None = None
    industry: str | None = None
    model_type: str | None = None
    valuation_summary: str | None = None
    assumption_breakdown: JSONObject | None = None
    data_freshness: JSONObject | None = None


@dataclass(frozen=True)
class FinancialHealthResult:
    reports: list[JSONObject]
    artifact_id: str | None


@dataclass(frozen=True)
class ModelSelectionResultDTO:
    model_type: str
    selected_model: str
    reasoning: str
    artifact_id: str | None
    selection_details: JSONObject
