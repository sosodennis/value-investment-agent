from __future__ import annotations

from src.agents.fundamental.workflow_orchestrator.application.dto import (
    FundamentalAppContextDTO,
)
from src.shared.kernel.types import JSONObject


def build_fundamental_app_context(
    intent_ctx: dict[str, object],
    resolved_ticker: str | None,
    *,
    status: str,
    model_type: str | None = None,
    valuation_summary: str | None = None,
    assumption_breakdown: JSONObject | None = None,
    data_freshness: JSONObject | None = None,
    assumption_risk_level: str | None = None,
    data_quality_flags: list[str] | None = None,
    time_alignment_status: str | None = None,
    forward_signal_summary: JSONObject | None = None,
    forward_signal_risk_level: str | None = None,
    forward_signal_evidence_count: int | None = None,
) -> FundamentalAppContextDTO:
    ticker = resolved_ticker or "UNKNOWN"
    company_name = ticker
    sector: str | None = None
    industry: str | None = None

    profile = intent_ctx.get("company_profile")
    if isinstance(profile, dict):
        name_raw = profile.get("name")
        sector_raw = profile.get("sector")
        industry_raw = profile.get("industry")
        if isinstance(name_raw, str) and name_raw:
            company_name = name_raw
        sector = sector_raw if isinstance(sector_raw, str) else None
        industry = industry_raw if isinstance(industry_raw, str) else None

    return FundamentalAppContextDTO(
        ticker=ticker,
        status=status,
        company_name=company_name,
        sector=sector,
        industry=industry,
        model_type=model_type,
        valuation_summary=valuation_summary,
        assumption_breakdown=assumption_breakdown,
        data_freshness=data_freshness,
        assumption_risk_level=assumption_risk_level,
        data_quality_flags=data_quality_flags,
        time_alignment_status=time_alignment_status,
        forward_signal_summary=forward_signal_summary,
        forward_signal_risk_level=forward_signal_risk_level,
        forward_signal_evidence_count=forward_signal_evidence_count,
    )
