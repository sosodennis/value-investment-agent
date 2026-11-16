"""Frozen label audits retain missing issuers without inventing source coverage."""

from __future__ import annotations

import copy
import gzip
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import audit_history_study_labels as audit  # noqa: E402


def filing(accession: str, period: str, accepted: str, form: str = "10-K") -> dict:
    return {
        "accession_number": accession,
        "report_period_end": period,
        "accepted_at": accepted,
        "form": form,
    }


@pytest.fixture
def frozen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[dict, Path]:
    decisions, issuers = [], []
    for i in range(1, 101):
        cik = f"{i:010d}"
        label = f"{cik}-17-000001" if i <= 91 else None
        decision = {
            "issuer_id": f"CIK:{cik}",
            "decision_accession": f"{cik}-16-000001",
            "decision_at": "2016-02-01T12:00:00Z",
            "label_accession": label,
            "label_missing_reason": None if label else "no_first_subsequent_original",
            "label_period_gap_days": 366 if i <= 90 else 731 if label else None,
            "label_horizon_matches_forecast": True
            if i <= 90
            else False
            if label
            else None,
        }
        snapshot = {
            "schema_version": "issue-359-issuer-snapshot-v1",
            "issuer_id": decision["issuer_id"],
            "cik": cik,
            "decision_accession": decision["decision_accession"],
            "filings": [
                filing(
                    decision["decision_accession"],
                    "2015-12-31",
                    decision["decision_at"],
                )
            ],
            "source_responses": [
                {
                    "source_id": "sec-submissions",
                    "response_sha256": "a" * 64,
                    "http_status": 200,
                    "uri": f"https://data.sec.gov/submissions/CIK{cik}.json",
                }
            ],
        }
        if label:
            snapshot["filings"].append(
                filing(
                    label,
                    "2016-12-31" if i <= 90 else "2017-12-31",
                    "2017-02-01T12:00:00Z" if i <= 90 else "2019-05-16T20:08:06Z",
                )
            )
        packed = gzip.compress(audit.canonical_bytes(snapshot), mtime=0)
        (tmp_path / f"{cik}.json.gz").write_bytes(packed)
        decisions.append(decision)
        issuers.append({**decision, "snapshot_sha256": audit.digest(packed)})
    inventory = {"issuers": issuers}
    manifest = {
        "issuer_decisions": decisions,
        "original_inventory": inventory,
        "original_inventory_digest": audit.digest(audit.canonical_bytes(inventory)),
    }
    monkeypatch.setattr(
        audit, "MANIFEST_DIGEST", audit.digest(audit.canonical_bytes(manifest))
    )
    return manifest, tmp_path


def repin(manifest: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest["original_inventory_digest"] = audit.digest(
        audit.canonical_bytes(manifest["original_inventory"])
    )
    monkeypatch.setattr(
        audit, "MANIFEST_DIGEST", audit.digest(audit.canonical_bytes(manifest))
    )


def snapshot(frozen: tuple[dict, Path], index: int = 0) -> tuple[dict, dict]:
    manifest, directory = frozen
    decision = manifest["issuer_decisions"][index]
    raw = gzip.decompress((directory / f"{index + 1:010d}.json.gz").read_bytes())
    return decision, json.loads(raw)


def test_retains_all_issuers_and_separates_missing_from_measured_mismatch(
    frozen: tuple[dict, Path],
) -> None:
    manifest, directory = frozen
    result = audit.audit_labels(manifest, directory)
    assert result["selected_issuers"] == 100
    assert result["maximum_eligible_label_pairs"] == 90
    assert result["disposition_counts"] == {
        "eligible_frozen_label": 90,
        "frozen_horizon_mismatch": 1,
        "no_later_annual_period_in_snapshot": 9,
    }
    assert len(result["rows"]) == 100
    assert result["rows"][90]["label_period_gap_days"] == 731
    assert all(r["frozen_horizon_eligible"] is None for r in result["rows"][91:])
    assert result["source_completeness_verified"] is False
    assert result["mapping_or_release_approved"] is False
    assert result["forecasts_executed"] == 0
    assert result["supported_history_threshold"] is None


def test_earliest_amendment_only_period_cannot_be_replaced_by_later_original(
    frozen: tuple[dict, Path],
) -> None:
    decision, source = snapshot(frozen, 91)
    source["filings"] += [
        filing("0000000092-17-000001", "2016-12-31", "2017-02-01T12:00:00Z", "10-K/A"),
        filing("0000000092-18-000001", "2017-12-31", "2018-02-01T12:00:00Z"),
    ]
    row = audit.audit_issuer(decision, source)
    assert row["selected_label"] is None
    assert row["disposition"] == "earliest_later_period_has_no_original"
    assert row["later_annual_accessions"] == [
        "0000000092-17-000001",
        "0000000092-18-000001",
    ]
    assert len(row["annual_filings"]) == 3


def test_selects_original_and_retains_amendments_and_all_other_annuals(
    frozen: tuple[dict, Path],
) -> None:
    decision, source = snapshot(frozen)
    source["filings"] += [
        filing("0000000001-17-000002", "2016-12-31", "2017-03-01T12:00:00Z", "10-K/A"),
        filing("0000000001-18-000001", "2017-12-31", "2018-02-01T12:00:00Z"),
        filing("0000000001-15-000001", "2016-01-01", "2015-12-01T12:00:00Z"),
    ]
    expected = audit.audit_issuer(decision, source)
    assert expected["selected_label"]["accession"] == "0000000001-17-000001"
    assert len(expected["annual_filings"]) == 5
    assert len(expected["later_annual_accessions"]) == 3
    source["filings"].reverse()
    assert audit.audit_issuer(decision, source) == expected


@pytest.mark.parametrize(
    "field,value",
    [
        ("decision_at", "2016-02-01T12:00:01Z"),
        ("label_accession", "0000000001-17-000999"),
        ("label_period_gap_days", 365),
        ("label_missing_reason", "invented"),
    ],
)
def test_rejects_frozen_date_accession_and_selection_substitution(
    frozen: tuple[dict, Path], field: str, value: object
) -> None:
    decision, source = snapshot(frozen)
    with pytest.raises(audit.DesignError, match="differs from frozen"):
        audit.audit_issuer({**decision, field: value}, source)


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("issuer", "snapshot issuer"),
        ("duplicate", "duplicate or conflicting"),
        ("ambiguous", "ambiguous equal availability"),
        ("timezone", "timezone"),
        ("form", "nonannual"),
        ("metadata", "submissions response metadata"),
    ],
)
def test_rejects_invalid_source_evidence(
    frozen: tuple[dict, Path], mutation: str, reason: str
) -> None:
    decision, source = snapshot(frozen)
    if mutation == "issuer":
        source["cik"] = "0000009999"
    elif mutation == "duplicate":
        source["filings"].append(copy.deepcopy(source["filings"][-1]))
    elif mutation == "ambiguous":
        source["filings"].append(
            {**source["filings"][-1], "accession_number": "0000000001-17-000002"}
        )
    elif mutation == "timezone":
        source["filings"][0]["accepted_at"] = "2016-02-01T12:00:00"
    elif mutation == "form":
        source["filings"][0]["form"] = "10-Q"
    else:
        source["source_responses"] = []
    with pytest.raises(audit.DesignError, match=reason):
        audit.audit_issuer(decision, source)


def test_digest_mismatch_and_missing_snapshots_fail_without_publication(
    frozen: tuple[dict, Path],
) -> None:
    manifest, directory = frozen
    path = directory / "0000000001.json.gz"
    original = path.read_bytes()
    path.write_bytes(original + b"corrupt")
    with pytest.raises(audit.DesignError, match="gzip snapshot digest"):
        audit.audit_labels(manifest, directory)
    path.unlink()
    with pytest.raises(FileNotFoundError):
        audit.audit_labels(manifest, directory)
    assert len(list(directory.iterdir())) == 99


def test_duplicate_json_fields_fail() -> None:
    with pytest.raises(audit.DesignError, match="duplicate JSON fields"):
        audit.decode_json(b'{"filings": [], "filings": []}')


def test_duplicate_or_omitted_issuers_cannot_reduce_denominator(
    frozen: tuple[dict, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, directory = frozen
    duplicate = copy.deepcopy(manifest)
    duplicate["issuer_decisions"].append(duplicate["issuer_decisions"][0])
    repin(duplicate, monkeypatch)
    with pytest.raises(audit.DesignError, match="unique fixed CIKs"):
        audit.audit_labels(duplicate, directory)
    manifest["original_inventory"]["issuers"].pop()
    repin(manifest, monkeypatch)
    with pytest.raises(audit.DesignError, match="all 100"):
        audit.audit_labels(manifest, directory)


def test_external_atomic_publication_reuses_bytes_sizes_and_mtimes(
    frozen: tuple[dict, Path], tmp_path: Path
) -> None:
    manifest, directory = frozen
    result = audit.audit_labels(manifest, directory)
    destination = tmp_path / "reports"
    assert audit.publish_report(destination, result)["wrote"] is True
    before = {
        p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in destination.iterdir()
    }
    assert audit.publish_report(destination, result)["wrote"] is False
    assert {
        p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in destination.iterdir()
    } == before
    report_path = destination / f"{audit.digest(audit.canonical_bytes(result))}.json"
    report_path.write_bytes(b"{}")
    with pytest.raises(audit.DesignError, match="corrupt"):
        audit.publish_report(destination, result)
