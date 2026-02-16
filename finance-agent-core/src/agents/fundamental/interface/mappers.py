from __future__ import annotations

from src.agents.fundamental.data.mappers import project_selection_reports
from src.agents.fundamental.domain.services import extract_latest_preview_metrics
from src.agents.fundamental.interface.contracts import FundamentalPreviewInputModel
from src.agents.fundamental.interface.formatters import format_fundamental_preview
from src.shared.kernel.types import JSONObject


def _derive_fundamental_preview_view_model(
    ctx: FundamentalPreviewInputModel,
    financial_reports: list[JSONObject] | None = None,
) -> JSONObject:
    ticker = ctx.ticker
    selected_model = ctx.selected_model or ctx.model_type or "Standard DCF"

    metrics: JSONObject = {}
    if financial_reports:
        selection_reports = project_selection_reports(financial_reports)
        preview_metrics = extract_latest_preview_metrics(selection_reports)
        if preview_metrics is not None:
            metrics = {
                "revenue_raw": preview_metrics.revenue_raw,
                "net_income_raw": preview_metrics.net_income_raw,
                "total_assets_raw": preview_metrics.total_assets_raw,
                "roe_ratio": preview_metrics.roe_ratio,
            }

    return {
        "ticker": ticker,
        "company_name": ctx.company_name,
        "selected_model": selected_model,
        "sector": ctx.sector,
        "industry": ctx.industry,
        "valuation_score": ctx.valuation_score,
        "status": ctx.status,
        "metrics": metrics,
    }


def summarize_fundamental_for_preview(
    ctx: FundamentalPreviewInputModel,
    financial_reports: list[JSONObject] | None = None,
) -> JSONObject:
    view_model = _derive_fundamental_preview_view_model(ctx, financial_reports)
    return format_fundamental_preview(view_model)
