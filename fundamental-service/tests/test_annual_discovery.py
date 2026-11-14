"""Issuer/date discovery retains the full SEC original-selection record."""

from datetime import UTC, datetime

import pytest

from fundamental_service.annual_discovery import (
    AnnualDiscoveryRequestV1,
    decode_history,
    decode_submissions,
    required_history_files,
    select_original_annuals,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest


def request(**updates):
    return AnnualDiscoveryRequestV1(
        **{
            "cik": "0000724910",
            "valuation_timestamp": datetime(2025, 6, 1, tzinfo=UTC),
            "declared_source_revision": "a" * 40,
            "supported_filing_years": (2023, 2024, 2025),
            **updates,
        }
    )


def row(year, **updates):
    return {
        "accessionNumber": f"0001376474-{str(year)[2:]}-000214",
        "filingDate": f"{year}-05-01",
        "acceptanceDateTime": f"{year}-05-01T16:00:00Z",
        "reportDate": f"{year}-03-31",
        "form": "10-K",
        "primaryDocument": "annual.htm",
        "isXBRL": 1,
        "isInlineXBRL": 1,
        **updates,
    }


def columns(*rows):
    return {key: [r[key] for r in rows] for key in rows[0]}


def source(*rows, files=None):
    return decode_submissions(
        canonical_bytes(
            {
                "cik": "724910",
                "tickers": ["UNTRUSTED-CURRENT-TICKER"],
                "filings": {"recent": columns(*rows), "files": files},
            }
        ),
        "0000724910",
    )


def select(value, *sources):
    return select_original_annuals(
        value, [(sha256_digest(s), s.filings.recent) for s in sources]
    )


def test_latest_originals_ignore_current_ticker_and_retain_all_exclusions():
    s = source(
        row(2022),
        row(2023),
        row(2024),
        row(2025),
        row(2026),
        row(2024, form="10-K/A", accessionNumber="0001376474-24-000215"),
    )
    result = select(request(), s)
    assert [r.report_period_end.year for r in result.selected] == [2024, 2025]
    assert not result.issue_codes
    assert len(result.dispositions) == 6
    by_accession = {d.accession_number: d for d in result.dispositions}
    assert by_accession[row(2026)["accessionNumber"]].issue_codes == (
        "ANNUAL_AFTER_VALUATION",
    )
    assert by_accession["0001376474-24-000215"].issue_codes == ("ANNUAL_FORM_EXCLUDED",)
    assert all(d.source_digests == (sha256_digest(s),) for d in result.dispositions)


def test_newest_unsupported_original_never_falls_back_to_old_supported_years():
    result = select(
        request(supported_filing_years=(2023, 2024)),
        source(row(2023), row(2024), row(2025)),
    )
    assert not result.selected
    assert result.issue_codes == ("FILING_RUNTIME_INCOMPATIBLE",)
    assert len(result.dispositions) == 3
    assert result.dispositions[-1].filing.report_period_end.year == 2025


def test_acceptance_is_the_cutoff_and_not_filing_date():
    s = source(
        row(2023), row(2024), row(2025, acceptanceDateTime="2025-05-01T16:00:01Z")
    )
    result = select(
        request(valuation_timestamp=datetime(2025, 5, 1, 16, tzinfo=UTC)), s
    )
    assert [r.report_period_end.year for r in result.selected] == [2023, 2024]
    at_cutoff = select(
        request(valuation_timestamp=datetime(2025, 5, 1, 16, 0, 1, tzinfo=UTC)), s
    )
    assert [r.report_period_end.year for r in at_cutoff.selected] == [2024, 2025]


def test_deterministic_order_and_identical_duplicate_accessions_keep_source_lineage():
    first = source(row(2024), row(2025))
    second = source(row(2025), row(2024))
    result = select(request(), first, second)
    assert result == select(request(), second, first)
    assert len(result.selected) == len(result.dispositions) == 2
    assert all(len(d.source_digests) == 2 for d in result.dispositions)


@pytest.mark.parametrize(
    "change",
    [
        {"acceptanceDateTime": None},
        {"acceptanceDateTime": "2025-05-01T16:00:00"},
        {"reportDate": ""},
        {"reportDate": "2025-06-01"},
        {"filingDate": "2025-03-30"},
        {"primaryDocument": "../foreign.htm"},
        {"isInlineXBRL": "unknown"},
        {"accessionNumber": "invalid-accession"},
    ],
)
def test_malformed_original_is_retained_and_blocks_selection(change):
    result = select(request(), source(row(2023), row(2024), row(2025, **change)))
    assert not result.selected
    assert "ANNUAL_METADATA_INVALID" in result.issue_codes
    assert len(result.dispositions) == 3
    assert (
        sum("ANNUAL_METADATA_INVALID" in d.issue_codes for d in result.dispositions)
        == 1
    )


def test_old_missing_primary_document_retains_failure_without_blocking_recent_originals():
    old = row(
        1996,
        accessionNumber="0000950134-96-000590",
        filingDate="1996-02-29",
        acceptanceDateTime="1996-02-29T05:00:00.000Z",
        reportDate="1995-12-31",
        primaryDocument="",
        isXBRL=0,
        isInlineXBRL=0,
    )
    result = select(request(), source(old, row(2024), row(2025)))
    assert [filing.report_period_end.year for filing in result.selected] == [2024, 2025]
    assert result.issue_codes == ()
    retained = next(
        d for d in result.dispositions if d.accession_number == old["accessionNumber"]
    )
    assert retained.filing is None
    assert retained.issue_codes == (
        "ANNUAL_METADATA_INVALID",
        "ANNUAL_OUTSIDE_LOOKBACK",
    )
    assert retained.source_digests


@pytest.mark.parametrize(
    "dates",
    [
        {"acceptanceDateTime": None},
        {"acceptanceDateTime": "1996-05-01T16:00:00"},
        {"acceptanceDateTime": "2025-05-01T16:00:00Z"},
        {"filingDate": "2025-05-01"},
        {"reportDate": "2025-03-31"},
        {"reportDate": ""},
    ],
)
def test_malformed_original_without_coherent_old_dates_still_blocks(dates):
    result = select(
        request(),
        source(row(1996, primaryDocument="", **dates), row(2024), row(2025)),
    )
    assert result.selected == ()
    assert "ANNUAL_METADATA_INVALID" in result.issue_codes


def test_old_malformed_duplicate_does_not_hide_current_accession_conflict():
    old = row(1996, accessionNumber=row(2025)["accessionNumber"], primaryDocument="")
    result = select(request(), source(old, row(2024), row(2025)))
    assert result.selected == ()
    assert "ANNUAL_ACCESSION_CONFLICT" in result.issue_codes


def test_malformed_original_on_the_lookback_boundary_still_blocks():
    result = select(
        request(lookback_days=31, original_count=1),
        source(row(2025, primaryDocument="")),
    )
    assert result.selected == ()
    assert result.issue_codes == (
        "ANNUAL_METADATA_INVALID",
        "ANNUAL_SOURCE_COUNT_INSUFFICIENT",
    )


def test_conflicting_duplicate_accessions_and_periods_are_not_replaced():
    s = source(
        row(2023), row(2024), row(2025), row(2025, primaryDocument="different.htm")
    )
    result = select(request(), s)
    assert "ANNUAL_ACCESSION_CONFLICT" in result.issue_codes and not result.selected
    assert len(result.dispositions) == 4
    result = select(request(), source(row(2024), row(2025, reportDate="2024-03-31")))
    assert result.issue_codes == ("ANNUAL_REPORT_PERIOD_CONFLICT",)
    assert not result.selected


def test_missing_originals_and_non_xbrl_latest_original_retain_refusal():
    result = select(request(), source(row(2025)))
    assert result.issue_codes == ("ANNUAL_SOURCE_COUNT_INSUFFICIENT",)
    result = select(request(), source(row(2023), row(2024), row(2025, isXBRL=0)))
    assert result.issue_codes == ("ANNUAL_XBRL_UNAVAILABLE",)
    assert not result.selected


def reference(cik="0000724910", number="001", **updates):
    return {
        "name": f"CIK{cik}-submissions-{number}.json",
        "filingCount": 2,
        "filingFrom": "2023-01-01",
        "filingTo": "2024-12-31",
        **updates,
    }


def test_relevant_history_is_explicit_bounded_and_independent_of_input_order():
    references = [
        reference(number="002"),
        reference(number="001"),
        reference(number="003", filingFrom="2000-01-01", filingTo="2001-01-01"),
        reference(number="004", filingFrom="2026-01-01", filingTo="2026-12-31"),
    ]
    names = required_history_files(source(row(2025), files=references), request())
    assert names == (
        "CIK0000724910-submissions-001.json",
        "CIK0000724910-submissions-002.json",
    )
    assert (
        required_history_files(
            source(row(2025), files=list(reversed(references))), request()
        )
        == names
    )
    with pytest.raises(ValueError, match="explicit discovery bound"):
        required_history_files(
            source(row(2025), files=references), request(maximum_history_files=1)
        )


@pytest.mark.parametrize(
    "references",
    [
        [reference(cik="0000320193")],
        [reference(), reference()],
        [reference(filingFrom="2025-01-01", filingTo="2024-01-01")],
    ],
)
def test_invalid_history_reference_cannot_create_incomplete_selection(references):
    with pytest.raises(ValueError):
        required_history_files(source(row(2025), files=references), request())


def test_recent_and_historical_rows_supply_the_same_original_selection():
    recent = source(row(2025))
    history = decode_history(canonical_bytes(columns(row(2023), row(2024))))
    result = select_original_annuals(
        request(), [("a" * 64, recent.filings.recent), ("b" * 64, history)]
    )
    assert [r.report_period_end.year for r in result.selected] == [2024, 2025]
    assert len(result.dispositions) == 3


def test_source_cik_columns_and_duplicate_keys_fail_at_decode():
    with pytest.raises(ValueError, match="CIK differs"):
        decode_submissions(
            canonical_bytes(
                {"cik": "320193", "filings": {"recent": columns(row(2025))}}
            ),
            "0000724910",
        )
    malformed = columns(row(2025))
    malformed["form"] = []
    with pytest.raises(ValueError, match="inconsistent lengths"):
        decode_history(canonical_bytes(malformed))
    with pytest.raises(ValueError, match="duplicate SEC JSON key"):
        decode_history(b'{"form":[],"form":[]}')


def test_sec_after_hours_acceptance_and_official_filing_date_remain_distinct():
    after_hours = row(
        2008,
        accessionNumber="0000724910-08-000006",
        acceptanceDateTime="2008-05-19T21:33:41.000Z",
        filingDate="2008-05-20",
        reportDate="2008-03-31",
        isXBRL=0,
        isInlineXBRL=0,
    )
    evidence = source(after_hours, row(2023), row(2024))
    result = select(
        request(valuation_timestamp=datetime(2024, 6, 1, tzinfo=UTC)), evidence
    )
    assert not result.issue_codes
    old = result.dispositions[0]
    assert old.issue_codes == ("ANNUAL_OUTSIDE_LOOKBACK",)
    assert old.filing.filing_date.isoformat() == "2008-05-20"
    assert old.filing.accepted_at == datetime(2008, 5, 19, 21, 33, 41, tzinfo=UTC)
    # A current after-hours original remains ineligible until both retained
    # acceptance and official filing date satisfy the decision cutoff.
    current = source(row(2023), row(2024, filingDate="2024-05-02"))
    before = select(
        request(valuation_timestamp=datetime(2024, 5, 1, 23, tzinfo=UTC)), current
    )
    assert before.issue_codes == ("ANNUAL_SOURCE_COUNT_INSUFFICIENT",)
    assert before.dispositions[-1].issue_codes == ("ANNUAL_AFTER_VALUATION",)
    after = select(
        request(valuation_timestamp=datetime(2024, 5, 2, tzinfo=UTC)), current
    )
    assert not after.issue_codes
