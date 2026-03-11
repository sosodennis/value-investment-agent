from __future__ import annotations

from src.agents.fundamental.model_selection.domain.entities import (
    FinancialHealthInsights,
    FundamentalSelectionReport,
)
from src.agents.fundamental.model_selection.domain.financial_math_service import (
    calculate_cagr,
    safe_ratio,
)


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


def calculate_revenue_cagr(
    financial_reports: list[FundamentalSelectionReport],
) -> float | None:
    revenue_series = [
        report.total_revenue
        for report in financial_reports
        if report.total_revenue is not None
    ]
    return calculate_cagr(revenue_series)


__all__ = [
    "build_latest_health_context",
    "calculate_revenue_cagr",
    "extract_latest_health_insights",
]
