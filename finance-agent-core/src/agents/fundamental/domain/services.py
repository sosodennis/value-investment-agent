from __future__ import annotations

from src.agents.fundamental.domain.entities import (
    FinancialHealthInsights,
    FundamentalReportsAdapter,
)
from src.agents.fundamental.domain.rules import calculate_cagr, safe_ratio
from src.agents.fundamental.domain.value_objects import MODEL_TYPE_BY_SELECTION
from src.common.types import JSONObject


def extract_latest_health_insights(
    financial_reports: list[JSONObject],
) -> FinancialHealthInsights | None:
    adapter = FundamentalReportsAdapter(financial_reports)
    latest_report = adapter.latest_report()
    if latest_report is None:
        return None

    base = latest_report.get("base")
    if not isinstance(base, dict):
        return None

    fy_raw = adapter.latest_value("base.fiscal_year")
    fiscal_year = str(fy_raw) if fy_raw is not None else "Unknown"

    net_income = adapter.latest_number("base.net_income")
    total_equity = adapter.latest_number("base.total_equity")
    operating_cash_flow = adapter.latest_number("base.operating_cash_flow")

    return FinancialHealthInsights(
        fiscal_year=fiscal_year,
        net_income=net_income,
        total_equity=total_equity,
        operating_cash_flow=operating_cash_flow,
        roe=safe_ratio(net_income, total_equity),
    )


def build_latest_health_context(financial_reports: list[JSONObject]) -> str:
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


def resolve_calculator_model_type(selected_model_value: str) -> str:
    model = MODEL_TYPE_BY_SELECTION.get(selected_model_value)
    if model is None:
        return MODEL_TYPE_BY_SELECTION["dcf_standard"].value
    return model.value


def calculate_revenue_cagr(financial_reports: list[JSONObject]) -> float | None:
    adapter = FundamentalReportsAdapter(financial_reports)
    revenue_series = adapter.numeric_series("base.total_revenue")
    return calculate_cagr(revenue_series)
