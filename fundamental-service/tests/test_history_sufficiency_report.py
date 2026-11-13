from datetime import UTC, date, datetime
from pathlib import Path

from fundamental_service.history_sufficiency_report import (
    DEFAULT_MANIFEST,
    Fact,
    Filing,
    _history_period_gaps,
    _microsoft_snapshot,
    _pilot_model,
    _select_fact,
    _wilson,
    _write_idempotently,
    build_history_sufficiency_report,
    first_subsequent_original_filing,
)
import json


def test_retained_microsoft_original_uses_sec_utc_acceptance_time():
    manifest = json.loads(DEFAULT_MANIFEST.read_bytes())
    row, matches = _microsoft_snapshot(DEFAULT_MANIFEST, manifest)
    assert matches is True
    available_at = datetime.fromisoformat(row["available_at"].replace("Z", "+00:00"))
    assert available_at > datetime(2024, 7, 30, 18, tzinfo=UTC)
    assert available_at == datetime(2024, 7, 30, 20, 6, 22, tzinfo=UTC)


def filing(
    accession: str,
    form: str,
    period_end: date,
    accepted_day: int,
) -> Filing:
    return Filing(
        issuer_id="CIK:0000000001",
        accession=accession,
        form=form,
        period_end=period_end,
        accepted_at=datetime(2024, 1, accepted_day, tzinfo=UTC),
    )


def test_point_in_time_fact_selection_excludes_later_publication():
    period_end = date(2023, 12, 31)
    valuation_at = datetime(2024, 2, 1, tzinfo=UTC)
    facts = (
        Fact(
            "revenue", "original", period_end, datetime(2024, 1, 20, tzinfo=UTC), "100"
        ),
        Fact(
            "revenue", "restated", period_end, datetime(2024, 3, 20, tzinfo=UTC), "110"
        ),
    )

    selected = _select_fact(facts, "revenue", period_end, valuation_at)

    assert selected is not None
    assert selected.accession == "original"


def test_first_subsequent_label_uses_original_and_does_not_skip_missing_period():
    decision = filing("decision", "10-K", date(2023, 12, 31), 10)
    next_amendment = filing("amendment", "10-K/A", date(2024, 12, 31), 20)
    later_original = filing("later", "10-K", date(2025, 12, 31), 21)

    assert (
        first_subsequent_original_filing(
            decision, (decision, next_amendment, later_original)
        )
        is None
    )

    next_original = filing("next-original", "10-K", date(2024, 12, 31), 19)
    selected = first_subsequent_original_filing(
        decision, (decision, next_amendment, next_original, later_original)
    )

    assert selected is next_original


def test_wilson_precision_policy_meets_ten_point_margin_at_one_hundred_clusters():
    interval = _wilson(50, 100)

    assert interval is not None
    assert (interval["upper"] - interval["lower"]) / 2 < 0.10


def test_history_window_reports_missing_annual_period_gap():
    gaps = _history_period_gaps((date(2019, 12, 31), date(2021, 12, 31)))

    assert gaps == [
        {
            "previous_period_end": "2019-12-31",
            "next_period_end": "2021-12-31",
            "elapsed_days": 731,
            "missing_annual_period_likely": True,
        }
    ]


def test_walk_forward_window_uses_original_filings_and_traces_next_filing_facts():
    filings = []
    facts = []
    for year in range(2018, 2024):
        period_end = date(year, 12, 31)
        accepted_at = datetime(year + 1, 2, 1, tzinfo=UTC)
        accession = str(year)
        filings.append(
            Filing("CIK:0000000001", accession, "10-K", period_end, accepted_at)
        )
        facts.append(
            Fact(
                "revenue",
                accession,
                period_end,
                accepted_at,
                str(year * 100),
                date(year, 1, 1),
            )
        )
        if year == 2020:
            filings.append(
                Filing(
                    "CIK:0000000001",
                    "2020-amendment",
                    "10-K/A",
                    period_end,
                    datetime(2022, 3, 1, tzinfo=UTC),
                )
            )

    result = _pilot_model("fcff_dcf", ("revenue",), filings, facts)
    decision = next(
        row
        for row in result["diagnostic_decision_rows"]
        if row["decision_accession"] == "2022"
    )

    assert decision["history_window_period_ends"] == [
        "2018-12-31",
        "2019-12-31",
        "2020-12-31",
        "2021-12-31",
        "2022-12-31",
    ]
    assert decision["history_period_gaps"] == []
    assert decision["three_of_five_proxy_rule_passes"] is True
    assert decision["next_original_filing_accession"] == "2023"
    assert decision["next_label_fields_present"] == ["revenue"]
    label_fact_id = decision["next_label_source_fact_ids"][0]
    label_fact = next(
        item
        for item in result["source_fact_catalog"]
        if item["fact_id"] == label_fact_id
    )
    assert label_fact["source_accession"] == "2023"
    assert label_fact["unit"] == "USD"
    assert label_fact["period_start"] == "2023-01-01"
    oos = result["oos_label_completeness"]
    assert oos["walk_forward_decisions"] == 2
    assert oos["decisions_with_next_original_filing"] == 1
    assert oos["complete_next_filing_labels"] == 1
    assert oos["candidate_gate"]["eligible_decisions_with_next_original_filing"] == 1
    assert oos["candidate_gate"]["complete_labels"] == 1


def test_oos_labels_include_decisions_that_fail_candidate_history_gate():
    filings = []
    facts = []
    for year in range(2018, 2025):
        period_end = date(year, 12, 31)
        accepted_at = datetime(year + 1, 2, 1, tzinfo=UTC)
        accession = str(year)
        filings.append(
            Filing("CIK:0000000001", accession, "10-K", period_end, accepted_at)
        )
        facts.append(
            Fact(
                "revenue",
                accession,
                period_end,
                accepted_at,
                str(year * 100),
                date(year, 1, 1),
            )
        )
        if year >= 2021:
            facts.append(
                Fact(
                    "operating_income",
                    accession,
                    period_end,
                    accepted_at,
                    str(year * 10),
                    date(year, 1, 1),
                )
            )

    result = _pilot_model("fcff_dcf", ("revenue", "operating_income"), filings, facts)
    decision = next(
        row
        for row in result["diagnostic_decision_rows"]
        if row["decision_accession"] == "2022"
    )
    oos = result["oos_label_completeness"]

    assert decision["three_of_five_proxy_rule_passes"] is False
    assert decision["next_label_fields_present"] == ["revenue", "operating_income"]
    assert oos["walk_forward_decisions"] == 3
    assert oos["decisions_with_next_original_filing"] == 2
    assert oos["complete_next_filing_labels"] == 2
    assert oos["candidate_gate"]["eligible_decisions_with_next_original_filing"] == 1
    assert oos["candidate_gate"]["complete_labels"] == 1


def test_report_json_is_reproducible_and_idempotent(tmp_path: Path):
    first = build_history_sufficiency_report(Path(DEFAULT_MANIFEST))
    second = build_history_sufficiency_report(Path(DEFAULT_MANIFEST))
    output = tmp_path / "history-report.json"

    assert first == second
    assert _write_idempotently(output, first) is True
    first_bytes = output.read_bytes()
    assert _write_idempotently(output, second) is False
    assert output.read_bytes() == first_bytes


def test_fixture_report_separates_primary_cohort_from_diagnostic_pilot():
    report = build_history_sufficiency_report(Path(DEFAULT_MANIFEST))

    assert report["threshold_decision"]["status"] == "underpowered"
    assert report["primary_cohort"]["issuer_cluster_count"] == 3
    assert report["primary_cohort"]["eligible_oos_fact_label_count"] == 0
    assert (
        report["primary_cohort"]["sampling_frame"]
        == "checked_in_fixture_inventory_not_a_representative_sampling_frame"
    )
    assert report["primary_cohort"]["industry_coverage"]["known_sic_issuer_count"] == 1
    assert report["primary_cohort"]["industry_coverage"]["unclassified_issuer_ids"] == [
        "CIK:0000320193",
        "CIK:0001318605",
    ]
    assert report["diagnostic_pilot"]["issuer_cluster_count"] == 1
    assert (
        report["diagnostic_pilot"]["models"]["fcff_dcf"]["threshold_decision"]["status"]
        == "underpowered"
    )
    assert (
        "analyst targets, consensus, Search, and LLM evidence are not read"
        in report["source_exclusions"]
    )
    included = report["primary_cohort"]["included_input_snapshots"]
    assert len(included) == 3
    microsoft = next(row for row in included if row["issuer_id"] == "CIK:0000789019")
    assert microsoft["index_size_warning_bytes"] == 1
    assert all(
        member["matches_canonical_sec_member"] for member in microsoft["source_members"]
    )
    excluded = report["primary_cohort"]["excluded_issuer_periods"]
    assert [row["accession_number"] for row in excluded] == ["0001104659-25-042659"]
    assert excluded[0]["exclusion_reason"] == "amendment_scope_unknown"
