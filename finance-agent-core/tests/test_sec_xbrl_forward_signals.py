from __future__ import annotations

from src.agents.fundamental.financial_statements.infrastructure.sec_xbrl.extract.report_contracts import (
    BaseFinancialModel,
    FinancialReport,
)
from src.agents.fundamental.forward_signals.infrastructure.sec_xbrl.forward_signals import (
    extract_forward_signals_from_xbrl_reports,
)
from src.agents.fundamental.shared.contracts.traceable import (
    ManualProvenance,
    TraceableField,
)


def _build_report(
    year: int, revenue: float, operating_income: float
) -> FinancialReport:
    base = BaseFinancialModel(
        fiscal_year=TraceableField(
            name="Fiscal Year",
            value=year,
            provenance=ManualProvenance(description="test"),
        ),
        total_revenue=TraceableField(
            name="Total Revenue",
            value=revenue,
            provenance=ManualProvenance(description="test"),
        ),
        operating_income=TraceableField(
            name="Operating Income",
            value=operating_income,
            provenance=ManualProvenance(description="test"),
        ),
    )
    return FinancialReport(base=base, extension=None, industry_type="Industrial")


def test_extract_forward_signals_from_xbrl_reports_builds_growth_and_margin_signals() -> (
    None
):
    reports = [
        _build_report(2022, revenue=100.0, operating_income=20.0),
        _build_report(2023, revenue=110.0, operating_income=22.0),
        _build_report(2024, revenue=130.0, operating_income=23.0),
    ]

    signals = extract_forward_signals_from_xbrl_reports(ticker="AAPL", reports=reports)
    metrics = {str(item.get("metric")): item for item in signals}

    assert "growth_outlook" in metrics
    assert "margin_outlook" in metrics
    assert metrics["growth_outlook"]["direction"] == "up"
    assert metrics["margin_outlook"]["direction"] == "down"
    assert metrics["growth_outlook"]["source_type"] == "xbrl_auto"
    assert metrics["growth_outlook"]["unit"] == "basis_points"
    assert isinstance(metrics["growth_outlook"]["evidence"], list)
    assert metrics["growth_outlook"]["evidence"][0]["source_url"].startswith(
        "https://www.sec.gov/edgar/search/"
    )


def test_extract_forward_signals_from_xbrl_reports_returns_empty_when_insufficient_data() -> (
    None
):
    reports = [_build_report(2024, revenue=130.0, operating_income=23.0)]
    signals = extract_forward_signals_from_xbrl_reports(ticker="AAPL", reports=reports)
    assert signals == []
