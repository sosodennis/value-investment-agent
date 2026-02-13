from __future__ import annotations

from collections.abc import Mapping

from src.agents.fundamental.domain.entities import (
    FinancialHealthInsights,
    FundamentalPreviewMetrics,
    FundamentalSelectionReport,
)
from src.agents.fundamental.domain.rules import calculate_cagr, safe_ratio
from src.agents.fundamental.domain.value_objects import MODEL_TYPE_BY_SELECTION


def extract_latest_health_insights(
    financial_reports: list[FundamentalSelectionReport],
) -> FinancialHealthInsights | None:
    if not financial_reports:
        return None

    latest_report = financial_reports[0]
    fiscal_year = latest_report.fiscal_year or "Unknown"

    net_income = latest_report.net_income
    total_equity = latest_report.total_equity
    operating_cash_flow = latest_report.operating_cash_flow

    return FinancialHealthInsights(
        fiscal_year=fiscal_year,
        net_income=net_income,
        total_equity=total_equity,
        operating_cash_flow=operating_cash_flow,
        roe=safe_ratio(net_income, total_equity),
    )


def build_latest_health_context(
    financial_reports: list[FundamentalSelectionReport],
) -> str:
    insights = extract_latest_health_insights(financial_reports)
    if insights is None:
        return ""

    lines = [f"\n\nFinancial Health Insights (FY{insights.fiscal_year}):"]
    if insights.net_income is not None:
        lines.append(f"- Net Income: ${insights.net_income:,.0f}")
    if insights.total_equity is not None:
        lines.append(f"\n- Total Equity: ${insights.total_equity:,.0f}")
    if insights.roe is not None:
        lines.append(f"\n- ROE: {insights.roe:.2%}")
    if insights.operating_cash_flow is not None:
        lines.append(f"\n- OCF: ${insights.operating_cash_flow:,.0f}")
    return "".join(lines)


def extract_latest_preview_metrics(
    financial_reports: list[FundamentalSelectionReport],
) -> FundamentalPreviewMetrics | None:
    if not financial_reports:
        return None

    latest = financial_reports[0]
    net_income = latest.net_income
    total_equity = latest.total_equity
    return FundamentalPreviewMetrics(
        revenue_raw=latest.total_revenue,
        net_income_raw=net_income,
        total_assets_raw=latest.total_assets,
        roe_ratio=safe_ratio(net_income, total_equity),
    )


def extract_equity_value_from_metrics(
    calculation_metrics: Mapping[str, object],
) -> object | None:
    intrinsic_value = calculation_metrics.get("intrinsic_value")
    if intrinsic_value is not None:
        return intrinsic_value
    equity_value = calculation_metrics.get("equity_value")
    if equity_value is not None:
        return equity_value
    return None


def resolve_calculator_model_type(selected_model_value: str) -> str:
    model = MODEL_TYPE_BY_SELECTION.get(selected_model_value)
    if model is None:
        return MODEL_TYPE_BY_SELECTION["dcf_standard"].value
    return model.value


def calculate_revenue_cagr(
    financial_reports: list[FundamentalSelectionReport],
) -> float | None:
    revenue_series = [
        report.total_revenue
        for report in financial_reports
        if report.total_revenue is not None
    ]
    return calculate_cagr(revenue_series)
