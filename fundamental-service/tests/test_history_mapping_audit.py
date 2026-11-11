from datetime import UTC, date, datetime

import pytest
from fundamental_service.history_mapping_audit import (
    MappingAuditError,
    _annual_usd_fact,
    _extract_revenue_concepts,
    _issuer_report,
)
from fundamental_service.history_sufficiency_report import Filing


def _accession(sequence: int) -> str:
    return f"0000000001-2{sequence:01d}-00000{sequence:01d}"


def _annual_filing(year: int, accession: str, form: str = "10-K") -> Filing:
    return Filing(
        issuer_id="CIK:0000000001",
        accession=accession,
        form=form,
        period_end=date(year, 12, 31),
        accepted_at=datetime(year + 1, 2, 1, 12, tzinfo=UTC),
    )


def _fact(
    accession: str,
    year: int,
    value: str,
    *,
    unit: str = "USD",
) -> dict[str, object]:
    return {
        "accession_number": accession,
        "form": "10-K",
        "unit": unit,
        "period_start": f"{year}-01-01",
        "period_end": f"{year}-12-31",
        "value": value,
        "fiscal_period": "FY",
        "fiscal_year": year,
        "filed": f"{year + 1}-02-01",
        "frame": f"CY{year}",
    }


def test_companyfacts_candidates_keep_only_cohort_accessions_and_target_periods():
    raw = {
        "cik": 1,
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "label": "Revenue",
                    "units": {
                        "USD": [
                            {
                                "accn": "decision",
                                "form": "10-K",
                                "start": "2022-01-01",
                                "end": "2022-12-31",
                                "val": 123.45,
                                "fp": "FY",
                            },
                            {
                                "accn": "future-restatement",
                                "form": "10-K",
                                "start": "2022-01-01",
                                "end": "2022-12-31",
                                "val": 999,
                                "fp": "FY",
                            },
                            {
                                "accn": "decision",
                                "form": "10-Q",
                                "start": "2022-10-01",
                                "end": "2022-12-31",
                                "val": 44,
                                "fp": "Q4",
                            },
                        ],
                        "shares": [
                            {
                                "accn": "decision",
                                "form": "10-K",
                                "start": "2022-01-01",
                                "end": "2022-12-31",
                                "val": 500,
                                "fp": "FY",
                            }
                        ],
                    },
                },
                "Assets": {
                    "label": "Assets",
                    "units": {
                        "USD": [
                            {
                                "accn": "decision",
                                "form": "10-K",
                                "start": "2022-01-01",
                                "end": "2022-12-31",
                                "val": 500,
                                "fp": "FY",
                            }
                        ]
                    },
                },
            }
        },
    }

    concepts = _extract_revenue_concepts(
        raw,
        cik="0000000001",
        allowed_accessions={"decision": "10-K"},
        target_periods=frozenset({date(2022, 12, 31)}),
    )

    assert [item["concept"] for item in concepts] == ["Revenues"]
    assert [item["unit"] for item in concepts[0]["facts"]] == ["USD", "shares"]
    assert [item["accession_number"] for item in concepts[0]["facts"]] == [
        "decision",
        "decision",
    ]
    assert concepts[0]["facts"][0]["value"] == "123.45"
    with pytest.raises(MappingAuditError, match="CIK differs"):
        _extract_revenue_concepts(
            {**raw, "cik": 2},
            cik="0000000001",
            allowed_accessions={"decision": "10-K"},
            target_periods=frozenset({date(2022, 12, 31)}),
        )


def test_revenue_candidate_screen_excludes_keyword_matches_and_components():
    def concept(value: str, label: str) -> dict[str, object]:
        return {
            "label": label,
            "units": {
                "USD": [
                    {
                        "accn": "decision",
                        "form": "10-K",
                        "start": "2022-01-01",
                        "end": "2022-12-31",
                        "val": value,
                        "fp": "FY",
                    }
                ]
            },
        }

    tags = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": concept(
            "120", "Revenue from contracts with customers"
        ),
        "Revenues": concept("120", "Revenue"),
        "SalesRevenueNet": concept("120", "Net sales revenue"),
        "SalesRevenueGoodsNet": concept("120", "Net revenue from goods"),
        "RevenueFromGrants": concept("120", "Revenue from grants"),
        "CostOfRevenue": concept("80", "Cost of revenue"),
        "ProceedsFromSaleOfAvailableForSaleSecuritiesDebt": concept(
            "40", "Proceeds from asset sales"
        ),
    }

    concepts = _extract_revenue_concepts(
        {
            "cik": 1,
            "facts": {"us-gaap": tags},
        },
        cik="0000000001",
        allowed_accessions={"decision": "10-K"},
        target_periods=frozenset({date(2022, 12, 31)}),
    )

    assert {item["concept"] for item in concepts} == {
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    }


def test_issuer_report_filters_non_total_tags_and_uses_first_subsequent_label():
    filings = [
        _annual_filing(year, _accession(year - 2017)) for year in range(2018, 2023)
    ]
    decision = filings[-1]
    following = _annual_filing(2023, _accession(6))
    later = _annual_filing(2024, _accession(7))
    filings.extend((following, later))
    facts = [
        _fact(item.accession, item.period_end.year, str(item.period_end.year * 10))
        for item in filings[:5]
    ]
    facts.extend(
        (
            _fact(following.accession, 2022, "999999"),
            _fact(following.accession, 2023, "20230"),
            _fact(later.accession, 2024, "20240"),
        )
    )
    issuer = {
        "issuer_id": decision.issuer_id,
        "cik": "0000000001",
        "decision_accession": decision.accession,
    }
    snapshot = {
        "filings": [
            {
                "accession_number": item.accession,
                "form": item.form,
                "report_period_end": item.period_end.isoformat(),
                "accepted_at": item.accepted_at.isoformat().replace("+00:00", "Z"),
            }
            for item in filings
        ]
    }
    evidence = {
        "source_response_sha256": "a" * 64,
        "concepts": [
            {"concept": "Revenues", "label": "Revenue", "facts": facts},
            {"concept": "CostOfRevenue", "label": "Cost of revenue", "facts": facts},
            {
                "concept": "SalesRevenueGoodsNet",
                "label": "Sales revenue, goods, net",
                "facts": facts,
            },
            {
                "concept": "ProceedsFromSaleOfAvailableForSaleSecuritiesDebt",
                "label": "Proceeds from asset sales",
                "facts": facts,
            },
        ],
    }

    result = _issuer_report(issuer, snapshot, evidence)

    assert [row["concept"] for row in result["candidate_concepts"]] == ["Revenues"]
    assert {
        row["concept"]
        for row in result["period_candidate_comparisons"][-1]["candidate_facts"]
    } == {"Revenues"}
    candidate = result["candidate_concepts"][0]
    assert candidate["history_fact_count"] == 5
    assert candidate["history_three_of_five_candidate"] is True
    decision_period = next(
        row
        for row in candidate["history_period_facts"]
        if row["period_end"] == decision.period_end.isoformat()
    )
    assert decision_period["value"] == str(decision.period_end.year * 10)
    assert candidate["first_subsequent_accession"] == following.accession
    assert candidate["first_subsequent_fact_id"] is not None
    assert (
        result["period_candidate_comparisons"][-1]["candidate_values_differ"] is False
    )


def test_annual_usd_fact_reports_same_time_value_conflicts():
    filing = _annual_filing(2022, _accession(5))
    concept = {
        "concept": "Revenues",
        "label": "Revenue",
        "facts": [
            _fact(filing.accession, 2022, "100"),
            _fact(filing.accession, 2022, "101"),
        ],
    }

    selected, conflict = _annual_usd_fact(
        concept,
        period_end=filing.period_end,
        filings_by_accession={filing.accession: filing},
        as_of=filing.accepted_at,
    )

    assert selected is None
    assert conflict is True
