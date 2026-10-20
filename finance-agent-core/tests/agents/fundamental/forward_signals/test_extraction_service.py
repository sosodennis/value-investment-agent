from __future__ import annotations

from src.agents.fundamental.subdomains.financial_statements.public import (
    FinancialReportModel,
)
from src.agents.fundamental.subdomains.forward_signals.application.extraction_service import (
    extract_forward_signals,
)


def _signal(signal_id: str) -> dict[str, object]:
    return {
        "signal_id": signal_id,
        "source_type": "mda",
        "metric": "growth_outlook",
        "direction": "up",
        "value": 80.0,
        "unit": "basis_points",
        "confidence": 0.61,
        "as_of": "2026-03-10T00:00:00Z",
        "evidence": [
            {
                "preview_text": signal_id,
                "full_text": signal_id,
                "source_url": "https://www.sec.gov/",
            }
        ],
    }


def test_extraction_uses_canonical_reports_and_combines_provider_results() -> None:
    reports_raw: list[dict[str, object]] = [
        {
            "industry_type": "FinancialServices",
            "base": {
                "fiscal_year": {"value": 2025},
                "total_revenue": {"value": 1200.0},
            },
        }
    ]
    observed: dict[str, object] = {}

    def extract_xbrl(
        *, ticker: str, reports: list[FinancialReportModel]
    ) -> list[dict[str, object]]:
        observed["ticker"] = ticker
        observed["report"] = reports[0]
        return [_signal("xbrl-signal")]

    def extract_text(
        *, ticker: str, rules_sector: str | None = None
    ) -> list[dict[str, object]]:
        observed["text_request"] = (ticker, rules_sector)
        return [_signal("text-signal")]

    signals = extract_forward_signals(
        ticker="BAC",
        reports_raw=reports_raw,
        extract_xbrl_fn=extract_xbrl,
        extract_text_fn=extract_text,
    )

    assert observed["ticker"] == "BAC"
    report = observed["report"]
    assert isinstance(report, FinancialReportModel)
    assert report.base.fiscal_year is not None
    assert report.base.fiscal_year.value == 2025
    assert observed["text_request"] == ("BAC", "financials")
    assert signals is not None
    assert [signal.signal_id for signal in signals] == [
        "xbrl-signal",
        "text-signal",
    ]
