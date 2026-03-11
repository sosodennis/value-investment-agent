from __future__ import annotations

from src.agents.fundamental.model_selection.interface.report_projection_service import (
    extract_latest_preview_metrics,
    project_selection_reports,
)
from src.shared.kernel.types import JSONObject


def project_fundamental_preview(
    ctx: JSONObject,
    financial_reports: list[JSONObject] | None = None,
) -> JSONObject:
    ticker = str(ctx.get("ticker", "UNKNOWN"))
    selected_model = str(
        ctx.get("selected_model") or ctx.get("model_type") or "Standard DCF"
    )

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
        "company_name": ctx.get("company_name", ticker),
        "selected_model": selected_model,
        "sector": ctx.get("sector", "Unknown"),
        "industry": ctx.get("industry", "Unknown"),
        "valuation_score": ctx.get("valuation_score"),
        "status": ctx.get("status", "done"),
        "metrics": metrics,
        "assumption_breakdown": ctx.get("assumption_breakdown"),
        "data_freshness": ctx.get("data_freshness"),
        "assumption_risk_level": ctx.get("assumption_risk_level"),
        "data_quality_flags": ctx.get("data_quality_flags"),
        "time_alignment_status": ctx.get("time_alignment_status"),
        "forward_signal_summary": ctx.get("forward_signal_summary"),
        "forward_signal_risk_level": ctx.get("forward_signal_risk_level"),
        "forward_signal_evidence_count": ctx.get("forward_signal_evidence_count"),
    }
