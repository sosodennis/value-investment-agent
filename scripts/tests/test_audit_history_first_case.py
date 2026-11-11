"""The first packet is fixed independently of forecast outcomes and keeps failures."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from audit_history_dqc_applicability import canonical_bytes, digest, write_report
from audit_history_first_case import audit, verified_report


def evidence() -> tuple[dict, dict]:
    issuers = []
    rows = []
    for index in range(1, 4):
        issuer = f"CIK:{index:010d}"
        origin = f"2016-02-0{index}T12:00:00Z"
        accessions = {}
        for role, year in (("history", 2014), ("decision", 2015), ("label", 2016)):
            accession = f"{index:010d}-{str(year + 1)[2:]}-000001"
            accessions[role] = accession
            accepted = origin if role == "decision" else f"{year + 1}-02-01T12:00:00Z"
            rows.append(
                {
                    "target": {
                        "issuer_id": issuer,
                        "cik": f"{index:010d}",
                        "accession": accession,
                        "role": role,
                        "form": "10-K",
                        "period_end": f"{year}-12-31",
                        "accepted_at": accepted,
                        "valuation_timestamp": accepted if role == "label" else origin,
                    },
                    "original_status": "validation_passed_unpublished",
                    "original_failure_code": None,
                    "original_result_digest": digest(accession.encode()),
                    "original_output_digest": digest((accession + "output").encode()),
                }
            )
        issuers.append(
            {
                "issuer_id": issuer,
                "decision_at": origin,
                "decision_accession": accessions["decision"],
                "label_accession": accessions["label"],
                "label_horizon_matches_forecast": True,
            }
        )
    rows[0]["original_status"] = "refused"
    rows[0]["original_failure_code"] = "SOURCE_ARCHIVE_SIZE_MISMATCH"
    subset = {
        "filing_count": 1,
        "rows": [
            {
                "target": copy.deepcopy(rows[0]["target"]),
                "status": "parsed_with_blockers",
                "blocking_codes": ["DQC.US.0015.2098"],
                "report_digest": "a" * 64,
            }
        ],
    }
    return {
        "issuer_count": 3,
        "filing_count": 9,
        "issuers": issuers,
        "rows": rows,
    }, subset


def test_frozen_order_keeps_failed_cases_and_does_not_rank_forecast_values() -> None:
    baseline, subset = evidence()
    first = audit(baseline, subset)
    assert first["issuer_count"] == 3 and first["filing_count"] == 9
    assert first["eligible_diagnostic_case_count"] == 2
    assert first["selected_case"]["issuer_id"] == "CIK:0000000002"
    refused = first["cases"][0]
    assert refused["ineligibility_reasons"] == ["PASSED_ORIGINAL_HISTORY_UNAVAILABLE"]
    assert (
        refused["filings"][0]["original_failure_code"] == "SOURCE_ARCHIVE_SIZE_MISMATCH"
    )
    assert refused["filings"][0]["current_status"] == "parsed_with_blockers"
    assert refused["filings"][0]["current_result_digest"] == "a" * 64
    baseline["rows"].reverse()
    baseline["issuers"].reverse()
    for issuer in baseline["issuers"]:
        issuer["forecast_error"] = -1000 if issuer["issuer_id"].endswith("3") else 1000
        issuer["mapping_gaps_discovered_later"] = 50
    assert audit(baseline, subset) == first
    assert all(case["forecast_ready"] is False for case in first["cases"])
    assert first["canonical_forecasts_executed"] == 0
    assert first["supported_history_threshold"] is None


def test_new_parser_evidence_can_enable_packet_without_approving_release() -> None:
    baseline, subset = evidence()
    subset["rows"][0]["status"] = "parsed_without_blockers"
    result = audit(baseline, subset)
    assert result["selected_case"]["issuer_id"] == "CIK:0000000001"
    assert result["selected_case"]["forecast_ready"] is False
    assert result["selected_case"]["canonical_publication_approved"] is False


def test_all_refusals_missing_labels_and_horizons_survive_null_selection() -> None:
    baseline, subset = evidence()
    for issuer in baseline["issuers"]:
        issuer["label_horizon_matches_forecast"] = False
    baseline["issuers"][1]["label_accession"] = None
    baseline["rows"] = [
        row
        for row in baseline["rows"]
        if not (
            row["target"]["issuer_id"] == "CIK:0000000002"
            and row["target"]["role"] == "label"
        )
    ]
    baseline["filing_count"] -= 1
    result = audit(baseline, subset)
    assert result["selected_case"] is None
    assert result["issuer_count"] == 3 and result["filing_count"] == 8
    assert "FIRST_ORIGINAL_LABEL_MISSING" in result["cases"][1]["ineligibility_reasons"]
    assert all(
        "LABEL_HORIZON_NOT_ELIGIBLE" in row["ineligibility_reasons"]
        for row in result["cases"]
    )


@pytest.mark.parametrize("collection", ["baseline", "subset"])
def test_duplicate_filing_is_rejected(collection: str) -> None:
    baseline, subset = evidence()
    document = baseline if collection == "baseline" else subset
    document["rows"].append(copy.deepcopy(document["rows"][0]))
    with pytest.raises(ValueError, match="repeats a frozen target"):
        audit(baseline, subset)


@pytest.mark.parametrize("mutation", ["foreign", "changed_target", "wrong_failure"])
def test_overlay_cannot_replace_other_original_evidence(mutation: str) -> None:
    baseline, subset = evidence()
    if mutation == "foreign":
        subset["rows"][0]["target"]["issuer_id"] = "CIK:9999999999"
    elif mutation == "changed_target":
        subset["rows"][0]["target"]["period_end"] = "2025-12-31"
    else:
        baseline["rows"][0]["original_failure_code"] = "PARSER_VALIDATION_BLOCKED"
    with pytest.raises(ValueError, match="original source-size refusal"):
        audit(baseline, subset)


@pytest.mark.parametrize("role", ["history", "label"])
def test_future_origin_input_or_in_sample_label_is_rejected(role: str) -> None:
    baseline, subset = evidence()
    row = next(
        row
        for row in baseline["rows"]
        if row["target"]["issuer_id"] == "CIK:0000000002"
        and row["target"]["role"] == role
    )
    row["target"]["accepted_at"] = (
        "2017-02-01T12:00:00Z" if role == "history" else "2015-02-01T12:00:00Z"
    )
    with pytest.raises(ValueError, match="after the decision"):
        audit(baseline, subset)


def test_frozen_first_label_cannot_be_replaced() -> None:
    baseline, subset = evidence()
    baseline["issuers"][1]["label_accession"] = "0000000002-18-000001"
    with pytest.raises(ValueError, match="frozen first original accession"):
        audit(baseline, subset)


def test_identical_packet_reuses_existing_bytes_and_corruption_fails(
    tmp_path: Path,
) -> None:
    baseline, subset = evidence()
    output = audit(baseline, subset)
    report = {
        "inputs": {"baseline_digest": digest(canonical_bytes(baseline))},
        "input_digest": digest(
            canonical_bytes({"baseline_digest": digest(canonical_bytes(baseline))})
        ),
        "output": output,
        "output_digest": digest(canonical_bytes(output)),
    }
    first = write_report(tmp_path, report)
    path = tmp_path / (first["report_digest"] + ".json")
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    assert verified_report(path, first["report_digest"]) == report
    assert write_report(tmp_path, report) == first | {"wrote": False}
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    damaged = copy.deepcopy(report)
    damaged["output"]["canonical_forecasts_executed"] = 1
    raw = canonical_bytes(damaged)
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="pinned digest"):
        verified_report(path, first["report_digest"])
    with pytest.raises(ValueError, match="payload digests"):
        verified_report(path, digest(raw))
    path.write_text(json.dumps(report, indent=2))
    with pytest.raises(ValueError, match="not canonical"):
        verified_report(path, digest(path.read_bytes()))
