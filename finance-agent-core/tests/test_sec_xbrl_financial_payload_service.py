from __future__ import annotations

from src.agents.fundamental.infrastructure.sec_xbrl.financial_payload_service import (
    fetch_financial_data,
)
from src.agents.fundamental.infrastructure.sec_xbrl.report_contracts import (
    BaseFinancialModel,
    FinancialReport,
)
from src.shared.kernel.traceable import ManualProvenance, TraceableField


def _report(year: int, *, selection_mode: str) -> FinancialReport:
    return FinancialReport(
        base=BaseFinancialModel(
            fiscal_year=TraceableField(
                name="Fiscal Year",
                value=str(year),
                provenance=ManualProvenance(description="test"),
            )
        ),
        industry_type="Industrial",
        extension_type="Industrial",
        filing_metadata={
            "form": "10-K",
            "matched_fiscal_year": year,
            "selection_mode": selection_mode,
        },
    )


def test_fetch_financial_data_prioritizes_latest_filing_then_descending_history(
    monkeypatch,
) -> None:
    latest = _report(2025, selection_mode="latest_available")
    by_year = {
        2024: _report(2024, selection_mode="fiscal_year_match"),
        2023: _report(2023, selection_mode="fiscal_year_match"),
    }
    requested_years: list[int] = []

    monkeypatch.setattr(
        "src.agents.fundamental.infrastructure.sec_xbrl.financial_payload_service.FinancialReportFactory.create_latest_report",
        staticmethod(lambda _ticker: latest),
    )

    def _create_report(_ticker: str, fiscal_year: int | None) -> FinancialReport:
        if fiscal_year is None:
            raise AssertionError("year-based create_report should not receive None")
        requested_years.append(fiscal_year)
        report = by_year.get(fiscal_year)
        if report is None:
            raise ValueError("not found")
        return report

    monkeypatch.setattr(
        "src.agents.fundamental.infrastructure.sec_xbrl.financial_payload_service.FinancialReportFactory.create_report",
        staticmethod(_create_report),
    )

    reports = fetch_financial_data("NVDA", years=3)

    years = [int(float(report.base.fiscal_year.value)) for report in reports]
    assert years == [2025, 2024, 2023]
    assert requested_years[:2] == [2024, 2023]
    assert reports[0].filing_metadata is not None
    assert reports[0].filing_metadata.get("selection_mode") == "latest_available"
