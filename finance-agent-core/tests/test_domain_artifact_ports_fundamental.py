from src.agents.fundamental.domain.entities import FundamentalReportsAdapter
from src.agents.fundamental.domain.services import (
    build_latest_health_context,
    extract_latest_health_insights,
)


def test_extract_latest_health_insights_from_traceable_fields() -> None:
    reports = [
        {
            "base": {
                "fiscal_year": {"value": "2024"},
                "net_income": {"value": 125.0},
                "total_equity": {"value": 500.0},
                "operating_cash_flow": {"value": 210.0},
            }
        }
    ]

    insights = extract_latest_health_insights(reports)

    assert insights is not None
    assert insights.fiscal_year == "2024"
    assert insights.net_income == 125.0
    assert insights.total_equity == 500.0
    assert insights.operating_cash_flow == 210.0
    assert insights.roe == 0.25


def test_extract_latest_health_insights_returns_none_when_base_missing() -> None:
    reports = [{"foo": "bar"}]

    insights = extract_latest_health_insights(reports)

    assert insights is None


def test_build_latest_health_context_omits_roe_when_equity_zero() -> None:
    reports = [
        {
            "base": {
                "fiscal_year": {"value": "2023"},
                "net_income": {"value": 100.0},
                "total_equity": {"value": 0.0},
                "operating_cash_flow": {"value": 50.0},
            }
        }
    ]

    context = build_latest_health_context(reports)

    assert "FY2023" in context
    assert "Net Income" in context
    assert "Total Equity" in context
    assert "OCF" in context
    assert "ROE" not in context


def test_fundamental_reports_adapter_extracts_series_and_coverage() -> None:
    reports = [
        {
            "base": {
                "total_revenue": {"value": 300.0},
                "net_income": {"value": 10.0},
            }
        },
        {"base": {"total_revenue": {"value": 200.0}}},
    ]
    adapter = FundamentalReportsAdapter(reports)

    assert adapter.latest_value("base.net_income") == 10.0
    assert adapter.numeric_series("base.total_revenue") == [300.0, 200.0]
    coverage = adapter.data_coverage({"base.net_income", "base.total_assets"})
    assert coverage["base.net_income"] is True
    assert coverage["base.total_assets"] is False
