from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

import pytest
import requests

from src.agents.fundamental.data.clients.sec_xbrl.factory import FinancialReportFactory
from src.agents.fundamental.data.clients.sec_xbrl.models import FinancialReport
from src.shared.kernel.traceable import TraceableField, XBRLProvenance

RUN_LIVE_TESTS = os.getenv("SEC_XBRL_LIVE_TESTS", "0").strip() == "1"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not RUN_LIVE_TESTS,
        reason="Set SEC_XBRL_LIVE_TESTS=1 to run live SEC golden tests.",
    ),
]


SEC_HEADERS = {"User-Agent": "ValueInvestmentAgent research@example.com"}
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}


@dataclass(frozen=True)
class GoldenCase:
    case_id: str
    ticker: str
    fiscal_year: int
    expected_industry: str
    field_path: str
    expected_concept: str
    cik: str
    companyconcept: str
    period_end: str
    unit: str = "USD"


CASES = [
    GoldenCase(
        case_id="aapl_assets_2025",
        ticker="AAPL",
        fiscal_year=2025,
        expected_industry="Industrial",
        field_path="base.total_assets",
        expected_concept="us-gaap:Assets",
        cik="0000320193",
        companyconcept="Assets",
        period_end="2025-09-27",
    ),
    GoldenCase(
        case_id="msft_assets_2025",
        ticker="MSFT",
        fiscal_year=2025,
        expected_industry="Industrial",
        field_path="base.total_assets",
        expected_concept="us-gaap:Assets",
        cik="0000789019",
        companyconcept="Assets",
        period_end="2025-06-30",
    ),
    GoldenCase(
        case_id="jpm_total_debt_2025",
        ticker="JPM",
        fiscal_year=2025,
        expected_industry="Financial Services",
        field_path="base.total_debt",
        expected_concept="us-gaap:LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
        cik="0000019617",
        companyconcept="LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
        period_end="2025-12-31",
    ),
    GoldenCase(
        case_id="o_revenue_2024",
        ticker="O",
        fiscal_year=2025,
        expected_industry="Real Estate",
        field_path="base.total_revenue",
        expected_concept="us-gaap:Revenues",
        cik="0000726728",
        companyconcept="Revenues",
        period_end="2024-12-31",
    ),
    GoldenCase(
        case_id="pld_revenue_2025",
        ticker="PLD",
        fiscal_year=2025,
        expected_industry="Real Estate",
        field_path="base.total_revenue",
        expected_concept="us-gaap:Revenues",
        cik="0001045609",
        companyconcept="Revenues",
        period_end="2025-12-31",
    ),
]


@lru_cache(maxsize=16)
def _load_report(ticker: str, fiscal_year: int) -> FinancialReport:
    return FinancialReportFactory.create_report(ticker, fiscal_year)


@lru_cache(maxsize=64)
def _fetch_companyconcept(cik: str, concept: str) -> dict:
    url = (
        f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{concept}.json"
    )
    response = requests.get(url, headers=SEC_HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def _extract_traceable(report: FinancialReport, path: str) -> TraceableField:
    current = report
    for segment in path.split("."):
        current = getattr(current, segment)
    if not isinstance(current, TraceableField):
        raise TypeError(f"{path} is not a TraceableField")
    return current


def _latest_annual_value(payload: dict, *, unit: str, period_end: str) -> float | None:
    units = payload.get("units")
    if not isinstance(units, dict):
        return None
    entries = units.get(unit)
    if not isinstance(entries, list):
        return None

    rows: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("end") != period_end:
            continue
        if entry.get("form") not in ANNUAL_FORMS:
            continue
        rows.append(entry)

    if not rows:
        return None

    rows.sort(
        key=lambda item: (str(item.get("filed", "")), str(item.get("accn", ""))),
        reverse=True,
    )
    value = rows[0].get("val")
    if not isinstance(value, int | float):
        return None
    return float(value)


@pytest.mark.parametrize("case", CASES, ids=[case.case_id for case in CASES])
def test_live_sec_golden_field_alignment(case: GoldenCase) -> None:
    report = _load_report(case.ticker, case.fiscal_year)
    assert report.industry_type == case.expected_industry

    field = _extract_traceable(report, case.field_path)
    assert field.value is not None
    assert isinstance(field.provenance, XBRLProvenance)
    assert field.provenance.concept == case.expected_concept
    assert case.period_end in field.provenance.period

    concept_payload = _fetch_companyconcept(case.cik, case.companyconcept)
    sec_value = _latest_annual_value(
        concept_payload,
        unit=case.unit,
        period_end=case.period_end,
    )
    assert sec_value is not None
    assert int(round(float(field.value))) == int(round(sec_value))
