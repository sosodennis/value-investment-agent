from __future__ import annotations

from src.agents.fundamental.domain.services import extract_latest_preview_metrics
from src.common.types import JSONObject


def derive_fundamental_preview_view_model(
    ctx: JSONObject,
    financial_reports: list[JSONObject] | None = None,
) -> JSONObject:
    ticker = str(ctx.get("ticker", "UNKNOWN"))
    selected_model = str(
        ctx.get("selected_model") or ctx.get("model_type") or "Standard DCF"
    )

    metrics: JSONObject = {}
    if financial_reports:
        preview_metrics = extract_latest_preview_metrics(financial_reports)
        if preview_metrics is not None:
            metrics = {
                "revenue_raw": preview_metrics.revenue_raw,
                "net_income_raw": preview_metrics.net_income_raw,
                "total_assets_raw": preview_metrics.total_assets_raw,
                "roe_ratio": preview_metrics.roe_ratio,
            }

    return {
        "ticker": ticker,
        "company_name": ctx.get("company_name", ticker),
        "selected_model": selected_model,
        "sector": ctx.get("sector", "Unknown"),
        "industry": ctx.get("industry", "Unknown"),
        "valuation_score": ctx.get("valuation_score"),
        "status": ctx.get("status", "done"),
        "metrics": metrics,
    }
