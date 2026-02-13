from src.agents.fundamental.domain.entities import FundamentalSelectionReport
from src.agents.fundamental.domain.services import (
    build_latest_health_context,
    calculate_revenue_cagr,
    extract_equity_value_from_metrics,
    extract_latest_health_insights,
)


def test_extract_latest_health_insights_from_traceable_fields() -> None:
    reports = [
        FundamentalSelectionReport(
            fiscal_year="2024",
            sic_code=None,
            total_revenue=None,
            net_income=125.0,
            total_equity=500.0,
            operating_cash_flow=210.0,
            total_assets=None,
            extension_ffo=None,
        )
    ]

    insights = extract_latest_health_insights(reports)

    assert insights is not None
    assert insights.fiscal_year == "2024"
    assert insights.net_income == 125.0
    assert insights.total_equity == 500.0
    assert insights.operating_cash_flow == 210.0
    assert insights.roe == 0.25


def test_extract_latest_health_insights_returns_none_when_base_missing() -> None:
    reports: list[FundamentalSelectionReport] = []

    insights = extract_latest_health_insights(reports)

    assert insights is None


def test_build_latest_health_context_omits_roe_when_equity_zero() -> None:
    reports = [
        FundamentalSelectionReport(
            fiscal_year="2023",
            sic_code=None,
            total_revenue=None,
            net_income=100.0,
            total_equity=0.0,
            operating_cash_flow=50.0,
            total_assets=None,
            extension_ffo=None,
        )
    ]

    context = build_latest_health_context(reports)

    assert "FY2023" in context
    assert "Net Income" in context
    assert "Total Equity" in context
    assert "OCF" in context
    assert "ROE" not in context


def test_calculate_revenue_cagr_uses_projection_series() -> None:
    reports = [
        FundamentalSelectionReport(
            fiscal_year="2024",
            sic_code=None,
            total_revenue=300.0,
            net_income=10.0,
            total_equity=None,
            operating_cash_flow=None,
            total_assets=None,
            extension_ffo=None,
        ),
        FundamentalSelectionReport(
            fiscal_year="2023",
            sic_code=None,
            total_revenue=200.0,
            net_income=None,
            total_equity=None,
            operating_cash_flow=None,
            total_assets=None,
            extension_ffo=None,
        ),
    ]
    cagr = calculate_revenue_cagr(reports)
    assert cagr is not None
    assert cagr > 0


def test_extract_equity_value_from_metrics_prefers_intrinsic_even_if_zero() -> None:
    metrics = {"intrinsic_value": 0.0, "equity_value": 99.0}
    assert extract_equity_value_from_metrics(metrics) == 0.0


def test_extract_equity_value_from_metrics_falls_back_to_equity() -> None:
    metrics = {"equity_value": 88.0}
    assert extract_equity_value_from_metrics(metrics) == 88.0
