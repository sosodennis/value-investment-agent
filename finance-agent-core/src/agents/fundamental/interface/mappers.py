from __future__ import annotations

from src.agents.fundamental.application.dto import FundamentalAppContextDTO
from src.agents.fundamental.application.view_models import (
    derive_fundamental_preview_view_model,
)
from src.agents.fundamental.interface.contracts import FundamentalPreviewInputModel
from src.agents.fundamental.interface.formatters import format_fundamental_preview
from src.shared.kernel.types import JSONObject


def build_mapper_context(
    intent_ctx: dict[str, object],
    resolved_ticker: str | None,
    *,
    status: str,
    model_type: str | None = None,
    valuation_summary: str | None = None,
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
    )


def summarize_fundamental_for_preview(
    ctx: FundamentalPreviewInputModel,
    financial_reports: list[JSONObject] | None = None,
) -> JSONObject:
    view_model = derive_fundamental_preview_view_model(
        ctx.model_dump(mode="json"),
        financial_reports,
    )
    return format_fundamental_preview(view_model)
