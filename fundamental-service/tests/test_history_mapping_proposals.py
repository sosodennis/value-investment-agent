import gzip
import json
from pathlib import Path

import pytest

from fundamental_service import history_mapping_proposals as mappings
from fundamental_service.serialization import sha256_digest

REVIEW_MANIFEST = (
    mappings.DEFAULT_DIRECTORY
    / "mapping_review/8b8513870f02c9522c52d4e1ac20ba93c551bb79fe3045eab956249d63cfd602.json.gz"
)


def _field(candidates: list[dict[str, object]]) -> dict[str, object]:
    return {
        "role": "history",
        "accession": "0001477932-16-007985",
        "period_end": "2015-09-30",
        "field": "revenue",
        "available_at": "2016-01-12T19:35:54Z",
        "amendment": False,
        "candidate_facts": candidates,
        "value_conflict": len(candidates) > 1,
        "missing_reason": None
        if candidates
        else "NO_ELIGIBLE_FACT_IN_COMPANYFACTS_PROFILE",
    }


def _candidate(concept: str, value: str = "100") -> dict[str, object]:
    row: dict[str, object] = {
        "concept": concept,
        "period_start": "2014-10-01",
        "period_end": "2015-09-30",
        "accession": "0001477932-16-007985",
        "unit": "USD",
        "value": value,
        "source_response_hash": "a" * 64,
        "rejection_reasons": [],
    }
    return {**row, "candidate_fact_id": sha256_digest(row)}


def test_unique_candidate_remains_a_provisional_unsigned_mapping_proposal() -> None:
    row = mappings.propose_field_mapping(
        _field([_candidate("Revenues")]), cik="0001539778", source_hash="a" * 64
    )
    assert row["reviewer_id"] is row["review_signature"] is None
    assert row["disposition"] == "proposed_exact_candidate_requires_review"
    preview = mappings._object(row["canonical_mapping_preview"], "preview")
    assert preview["status"] == "provisional"
    assert preview["reviewer"] is preview["reviewed_at"] is None
    assert preview["decision_id"] == row["decision_id"]


@pytest.mark.parametrize(
    "candidates",
    (
        [_candidate("Revenues"), _candidate("Revenues", "200")],
        [_candidate("Revenues"), _candidate("SalesRevenueNet")],
    ),
)
def test_competing_values_or_meanings_remain_unresolved(
    candidates: list[dict[str, object]],
) -> None:
    row = mappings.propose_field_mapping(
        _field(candidates), cik="0001539778", source_hash="a" * 64
    )
    assert row["disposition"] == "unresolved_competing_candidates"
    assert row["canonical_mapping_preview"] is row["selected_candidate"] is None
    assert len(mappings._array(row["candidate_fact_ids"], "candidate ids")) == 2


def test_missing_role_is_not_proposed_as_zero_and_source_tampering_is_rejected() -> (
    None
):
    row = mappings.propose_field_mapping(
        _field([]), cik="0001539778", source_hash="a" * 64
    )
    assert row["selected_candidate"] is None
    assert row["disposition"] == "unresolved_no_eligible_candidate"
    assert row["missing_reason"] == "NO_ELIGIBLE_FACT_IN_COMPANYFACTS_PROFILE"
    with pytest.raises(ValueError, match="source hash mismatch"):
        mappings.propose_field_mapping(
            _field([_candidate("Revenues")]), cik="0001539778", source_hash="b" * 64
        )


def test_all_fixed_issuers_and_failures_survive_unchanged_proposal_rerun(
    tmp_path: Path,
) -> None:
    package = mappings.build_mapping_proposals(review_manifest_path=REVIEW_MANIFEST)
    assert package["selected_issuer_count"] == 100
    assert package["approved_mapping_count"] == package["canonical_fact_count"] == 0
    assert package["supported_history_threshold"] is None
    rows = [
        mappings._object(row, "issuer")
        for row in mappings._array(package["issuer_rows"], "issuers")
    ]
    assert len({row["cik"] for row in rows}) == 100
    decisions = [
        mappings._object(d, "decision")
        for row in rows
        for d in mappings._array(row["mapping_decisions"], "decisions")
    ]
    counts = mappings._object(package["dispositions"], "counts")
    assert all(isinstance(value, int) for value in counts.values())
    assert len(decisions) == sum(
        value for value in counts.values() if isinstance(value, int)
    )
    assert all(
        row["reviewer_id"] is row["review_signature"] is None for row in decisions
    )
    assert any(
        row["disposition"] == "unresolved_no_eligible_candidate" for row in decisions
    )
    first = mappings.write_mapping_proposals(package, tmp_path)
    original = {p: p.read_bytes() for p in tmp_path.rglob("*.gz")}
    repeat = mappings.write_mapping_proposals(
        mappings.build_mapping_proposals(review_manifest_path=REVIEW_MANIFEST), tmp_path
    )
    assert first["output_digest"] == repeat["output_digest"]
    assert repeat["wrote"] is False
    assert original == {p: p.read_bytes() for p in original}


def test_altered_issuer_artifact_is_rejected_before_proposals(tmp_path: Path) -> None:
    manifest = json.loads(gzip.decompress(REVIEW_MANIFEST.read_bytes()))
    ref = manifest["issuer_refs"][0]
    manifest_dir = tmp_path / "mapping_review"
    issuer_dir = tmp_path / "mapping_issuers"
    manifest_dir.mkdir()
    issuer_dir.mkdir()
    manifest_path = manifest_dir / REVIEW_MANIFEST.name
    manifest_path.write_bytes(REVIEW_MANIFEST.read_bytes())
    (issuer_dir / (ref["sha256"] + ".json.gz")).write_bytes(
        gzip.compress(b"{}", mtime=0)
    )
    with pytest.raises(ValueError, match="input digest mismatch"):
        mappings.build_mapping_proposals(review_manifest_path=manifest_path)
