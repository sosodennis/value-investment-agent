"""Readiness joins preserve old failures without manufacturing current approvals."""

from __future__ import annotations

import copy
import gzip
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import audit_history_study_readiness as audit  # noqa: E402


def make_archive(
    tmp_path: Path, *, members: list[tuple[str, bytes]] | None = None
) -> tuple[dict, str]:
    raw = audit.canonical_bytes({"retained_failure": "PARSER_VALIDATION_BLOCKED"})
    name = f"evidence/{audit.digest(raw)}.json.gz"
    packed = gzip.compress(raw, mtime=0)
    entries = members if members is not None else [(name, packed)]
    with tarfile.open(tmp_path / "evidence.tar.gz", "w:gz") as tar:
        for path, content in entries:
            member = tarfile.TarInfo(path)
            member.size = len(content)
            tar.addfile(member, io.BytesIO(content))
    manifest = {
        "files": [
            {"path": path, "byte_length": len(content), "sha256": audit.digest(content)}
            for path, content in dict(entries).items()
        ],
        "archive_sha256": audit.digest((tmp_path / "evidence.tar.gz").read_bytes()),
    }
    manifest_raw = audit.canonical_bytes(manifest)
    (tmp_path / "manifest.json").write_bytes(manifest_raw)
    return {
        "archive_manifest_filename": "manifest.json",
        "archive_manifest_sha256": audit.digest(manifest_raw),
        "archive_filename": "evidence.tar.gz",
        "archive_byte_length": (tmp_path / "evidence.tar.gz").stat().st_size,
        "archive_sha256": manifest["archive_sha256"],
        "file_count": len(manifest["files"]),
    }, name


def test_archive_checks_packed_and_canonical_identity_without_extracting(
    tmp_path: Path,
) -> None:
    reference, name = make_archive(tmp_path)
    before = sorted(tmp_path.iterdir())
    with audit.open_archive(tmp_path, reference) as archive:
        assert archive.document(name) == {
            "retained_failure": "PARSER_VALIDATION_BLOCKED"
        }
        assert archive.consumed == {name: Path(name).name.removesuffix(".json.gz")}
        with pytest.raises(audit.DesignError, match="content digest"):
            archive.document(name, "0" * 64)
    assert sorted(tmp_path.iterdir()) == before


@pytest.mark.parametrize("mutation", ["manifest", "archive"])
def test_corrupt_outer_archive_fails_closed(tmp_path: Path, mutation: str) -> None:
    reference, _ = make_archive(tmp_path)
    path = tmp_path / ("manifest.json" if mutation == "manifest" else "evidence.tar.gz")
    path.write_bytes(path.read_bytes() + b"corrupt")
    with pytest.raises(audit.DesignError, match="digest"):
        with audit.open_archive(tmp_path, reference):
            pytest.fail("corrupt input was accepted")


@pytest.mark.parametrize("kind", ["duplicate", "traversal", "absolute"])
def test_archive_rejects_ambiguous_or_unsafe_members(tmp_path: Path, kind: str) -> None:
    entries = [("same.json.gz", b"payload")]
    if kind == "duplicate":
        entries *= 2
    else:
        entries = [
            (
                "../escape.json.gz" if kind == "traversal" else "/escape.json.gz",
                b"payload",
            )
        ]
    reference, _ = make_archive(tmp_path, members=entries)
    with pytest.raises(audit.DesignError, match="archive member"):
        with audit.open_archive(tmp_path, reference):
            pytest.fail("unsafe archive was accepted")


def test_member_bytes_and_noncanonical_documents_are_rejected(tmp_path: Path) -> None:
    raw = b'{"z": 1, "a": 2}'
    name = f"evidence/{audit.digest(raw)}.json.gz"
    reference, _ = make_archive(tmp_path, members=[(name, gzip.compress(raw, mtime=0))])
    with audit.open_archive(tmp_path, reference) as archive:
        with pytest.raises(audit.DesignError, match="canonical JSON"):
            archive.document(name)
        archive.members[name]["sha256"] = "0" * 64
        with pytest.raises(audit.DesignError, match="packed digest"):
            archive.document(name)


class Records:
    def __init__(self, records: dict[str, dict]) -> None:
        self.records = records

    def reference(self, value: object) -> dict:
        return self.records[value["path"]]


@pytest.fixture
def mappings() -> tuple[Records, dict, dict]:
    target = {
        "issuer_id": "CIK:0001282637",
        "cik": "0001282637",
        "accession": "0001282637-16-000009",
        "period_end": "2015-12-31",
        "accepted_at": "2016-02-12T16:26:17Z",
        "form": "10-K",
        "role": "decision",
        "valuation_timestamp": "2016-02-12T16:26:17Z",
    }
    issuer = {
        "issuer_id": target["issuer_id"],
        "decision_accession": target["accession"],
        "decision_at": target["accepted_at"],
        "mapping_proposal": {"path": "proposal", "sha256": "a" * 64},
        "mapping_packet": {"path": "packet", "sha256": "b" * 64},
    }
    common = {
        "cik": target["cik"],
        "decision_accession": target["accession"],
        "decision_at": target["accepted_at"],
    }
    row = {
        "accession": target["accession"],
        "field": "contract_assets",
        "period_end": target["period_end"],
        "available_at": target["accepted_at"],
        "amendment": False,
        "role": "history",
        "decision_id": "c" * 64,
        "disposition": "unresolved_no_eligible_candidate",
        "missing_reason": "NO_ELIGIBLE_FACT_IN_COMPANYFACTS_PROFILE",
        "value_conflict": False,
        "candidate_fact_ids": [],
        "rejected_candidate_ids": [],
        "mapping_version": "unapproved-v1",
    }
    records = Records(
        {
            "proposal": {
                **common,
                "input_issuer_digest": "b" * 64,
                "mapping_decisions": [row],
            },
            "packet": {**common, "field_rows": [copy.deepcopy(row)]},
        }
    )
    return records, issuer, {audit.target_key(target): target}


def test_companyfacts_missingness_is_preserved_as_unapproved_candidate_gap(
    mappings: tuple,
) -> None:
    records, issuer, targets = mappings
    result = audit.mapping_records(records, issuer, targets)
    row = next(iter(result.values()))
    assert (
        row["authority"]
        == "archived_companyfacts_proposals_not_original_disclosure_adjudication"
    )
    assert (
        row["fields"][0]["missing_reason"] == "NO_ELIGIBLE_FACT_IN_COMPANYFACTS_PROFILE"
    )
    assert row["fields"][0]["disposition"] == "unresolved_no_eligible_candidate"
    assert row["fields"][0]["candidate_fact_ids"] == []
    assert "value" not in row["fields"][0]


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "omitted",
        "period",
        "availability",
        "amendment",
        "role",
        "issuer",
        "accession",
        "packet_digest",
    ],
)
def test_mapping_identity_and_omission_controls(mappings: tuple, mutation: str) -> None:
    records, issuer, targets = mappings
    proposal = records.records["proposal"]
    row = proposal["mapping_decisions"][0]
    if mutation == "duplicate":
        proposal["mapping_decisions"].append(copy.deepcopy(row))
    elif mutation == "omitted":
        proposal["mapping_decisions"] = []
    elif mutation == "period":
        row["period_end"] = "2016-12-31"
    elif mutation == "availability":
        row["available_at"] = "2017-02-12T16:26:17Z"
    elif mutation == "amendment":
        row["amendment"] = True
    elif mutation == "role":
        row["role"] = "label"
    elif mutation == "issuer":
        proposal["cik"] = "0000000001"
    elif mutation == "accession":
        row["accession"] = "0001282637-17-000001"
    else:
        proposal["input_issuer_digest"] = "d" * 64
    with pytest.raises(audit.DesignError):
        audit.mapping_records(records, issuer, targets)


def test_filing_join_cannot_drop_failed_target_or_replace_issuer(
    mappings: tuple,
) -> None:
    records, _, targets = mappings
    target = next(iter(targets.values()))
    records.records["diagnosis"] = {
        "target": target,
        "status": "original_sources_incomplete",
        "frozen_code": "XBRL_ENTRYPOINT_UNRESOLVED",
    }
    checkpoint = {
        "inputs": {
            "roots": {
                "integrity": [{"path": "diagnosis/filings/item", "sha256": "a" * 64}]
            }
        }
    }
    records.records["diagnosis/filings/item"] = records.records["diagnosis"]
    result = audit.source_records(records, checkpoint, "integrity", targets)
    assert (
        next(iter(result.values()))["record"]["frozen_code"]
        == "XBRL_ENTRYPOINT_UNRESOLVED"
    )
    checkpoint["inputs"]["roots"]["integrity"] = []
    with pytest.raises(audit.DesignError, match="every fixed filing"):
        audit.source_records(records, checkpoint, "integrity", targets)


def test_content_addressed_publication_preserves_bytes_and_mtime(
    tmp_path: Path,
) -> None:
    report = {
        "failure": "abstain",
        "exact": 0,
        "conditional_issuers": 1,
        "supported_history_threshold": None,
    }
    first = audit.publish_report(tmp_path, report)
    path = tmp_path / f"{first['report_digest']}.json"
    before = path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_size
    second = audit.publish_report(tmp_path, report)
    assert second == {"report_digest": first["report_digest"], "wrote": False}
    assert (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_size) == before
    assert json.loads(path.read_bytes())["supported_history_threshold"] is None


class CohortArchive(Records):
    def document(self, path: str, expected: str | None = None) -> dict:
        return self.records["checkpoint" if "/checkpoint/" in path else "readiness"]


@pytest.fixture
def cohort(monkeypatch: pytest.MonkeyPatch, mappings: tuple) -> tuple:
    template, template_issuer, template_targets = mappings
    source_target = next(iter(template_targets.values()))
    targets, old_issuers, labels, refs = [], [], [], []
    records = {}
    roots = {
        "originals": [],
        "integrity_source_observations": [],
        "legacy_concept_discovery": [],
    }
    for i in range(1, 101):
        cik = f"{i:010d}"
        issuer = f"CIK:{cik}"
        old = {
            **template_issuer,
            "issuer_id": issuer,
            "decision_accession": f"{cik}-16-000001",
            "mapping_proposal": {"path": f"proposal{i}", "sha256": "a" * 64},
            "mapping_packet": {"path": f"packet{i}", "sha256": "b" * 64},
        }
        old_issuers.append(old)
        labels.append(
            {
                "issuer_id": issuer,
                "decision": {
                    "accession": old["decision_accession"],
                    "accepted_at": old["decision_at"],
                },
            }
        )
        proposal_rows = []
        # 89 six-target issuers plus 11 five-target issuers = 589.
        for j in range(6 if i <= 89 else 5):
            target = {
                **source_target,
                "cik": cik,
                "issuer_id": issuer,
                "accession": f"{cik}-16-{j + 1:06d}",
                "role": "decision" if j == 0 else "history",
            }
            targets.append(target)
            source = copy.deepcopy(template.records["proposal"]["mapping_decisions"][0])
            source["accession"] = target["accession"]
            proposal_rows.append(source)
            result_digest = audit.digest(audit.canonical_bytes(target))
            refs.append({"sha256": result_digest})
            roots["originals"].append(
                {
                    "original_path": f"results/{result_digest}.json.gz",
                    "sha256": result_digest,
                }
            )
            for category in (
                "integrity_source_observations",
                "legacy_concept_discovery",
            ):
                path = f"{category}/filings/{i}-{j}"
                roots[category].append({"path": path, "sha256": result_digest})
                records[path] = {
                    "target": target,
                    "frozen_result_digest": result_digest,
                    "frozen_code": None if i == 1 else "PARSER_VALIDATION_BLOCKED",
                    "status": "index_sizes_consistent"
                    if i == 1
                    else "original_sources_incomplete",
                    "discovery_status": "no_retained_original_zip_and_xml",
                }
        common = {
            "cik": cik,
            "decision_accession": old["decision_accession"],
            "decision_at": old["decision_at"],
        }
        records[f"proposal{i}"] = {
            **common,
            "input_issuer_digest": "b" * 64,
            "mapping_decisions": proposal_rows,
        }
        records[f"packet{i}"] = {**common, "field_rows": copy.deepcopy(proposal_rows)}
    records["checkpoint"] = {"inputs": {"roots": roots, "source_commit": "f" * 40}}
    records["readiness"] = {
        "inputs": {"source_commit": "e" * 40},
        "output": {"issuers": old_issuers},
    }
    manifest = {
        "original_inventory": {"targets": targets},
        "original_filing_outcome_refs": refs,
        "source_checkpoint_digest": "d" * 64,
    }
    monkeypatch.setattr(
        audit,
        "audit_labels",
        lambda *_: {
            "rows": labels,
            "disposition_counts": {
                "eligible_frozen_label": 90,
                "frozen_horizon_mismatch": 1,
                "no_later_annual_period_in_snapshot": 9,
            },
            "maximum_eligible_label_pairs": 90,
        },
    )
    conditional = {
        "arm_summaries": [
            {
                "issuer_id": "CIK:0000000001",
                "model": "fcff_dcf",
                "years": 3,
                "conditional_comparisons": 3125,
            }
        ],
        "independent_conditional_issuers": 1,
    }
    return manifest, CohortArchive(records), conditional


def test_full_join_retains_100_issuers_589_targets_and_independent_denominator(
    cohort: tuple, tmp_path: Path
) -> None:
    manifest, archive, conditional = cohort
    first = audit.audit_readiness(manifest, tmp_path, archive, conditional)
    second = audit.audit_readiness(manifest, tmp_path, archive, conditional)
    assert audit.canonical_bytes(first) == audit.canonical_bytes(second)
    assert len(first["rows"]) == 100
    assert sum(len(row["filing_targets"]) for row in first["rows"]) == 589
    assert first["archived_source_failure_code_counts"] == {
        "PARSER_VALIDATION_BLOCKED": 583
    }
    assert first["archived_source_no_failure_code_count"] == 6
    assert first["complete_exact_study_cases"] == 0
    assert first["verified_issuers"] == 0
    assert first["independent_conditional_issuers"] == 1
    assert first["maximum_eligible_label_pairs"] == 90
    assert first["supported_history_threshold"] is None
    assert all(row["exact_study_case"] is False for row in first["rows"])
    assert (
        first["rows"][1]["current_evidence_status"]
        == "not_supplied_in_explicit_evidence_index"
    )
    assert all(
        f["current_parser_validation"] == "not_reexecuted_by_readiness_audit"
        for row in first["rows"]
        for f in row["filing_targets"]
    )
    assert first["mapping_or_release_approved"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        "target_duplicate",
        "target_omitted",
        "source_duplicate",
        "source_omitted",
        "source_foreign",
        "future",
        "conflicting_result",
        "issuer_omitted",
        "conditional_foreign",
    ],
)
def test_full_join_refuses_ambiguous_incomplete_or_leaking_evidence(
    cohort: tuple, tmp_path: Path, mutation: str
) -> None:
    manifest, archive, conditional = cohort
    targets = manifest["original_inventory"]["targets"]
    roots = archive.records["checkpoint"]["inputs"]["roots"]
    source_refs = roots["integrity_source_observations"]
    if mutation == "target_duplicate":
        targets[-1] = targets[0]
    elif mutation == "target_omitted":
        targets.pop()
    elif mutation == "source_duplicate":
        source_refs.append(source_refs[0])
    elif mutation == "source_omitted":
        source_refs.pop()
    elif mutation == "source_foreign":
        archive.records[source_refs[0]["path"]]["target"] = {
            **targets[0],
            "issuer_id": "CIK:9999999999",
        }
    elif mutation == "future":
        targets[0]["accepted_at"] = "2017-02-12T16:26:17Z"
    elif mutation == "conflicting_result":
        archive.records[roots["legacy_concept_discovery"][0]["path"]][
            "frozen_result_digest"
        ] = "0" * 64
    elif mutation == "issuer_omitted":
        archive.records["readiness"]["output"]["issuers"].pop()
    else:
        conditional["arm_summaries"][0]["issuer_id"] = "CIK:9999999999"
    with pytest.raises(audit.DesignError):
        audit.audit_readiness(manifest, tmp_path, archive, conditional)


def test_strict_evidence_index_accepts_json_tuple_arrays_and_rejects_duplicate_keys() -> (
    None
):
    reference = {"path": "artifact.json", "sha256": "a" * 64}
    document = {
        "schema_version": "history-study-evidence-index.v1",
        "fixed_manifest_digest": "b" * 64,
        "runtime": {
            "python": "3.11.15",
            "implementation": "CPython",
            "machine": "arm64",
            "system": "Darwin",
            "packages": {},
            "uv_lock_digest": "c" * 64,
        },
        "entries": [
            {"request": reference, "forecast": reference, "comparison": reference}
        ],
    }
    raw = audit.canonical_bytes(document)
    assert len(audit.decode_evidence_index(raw).entries) == 1
    with pytest.raises(audit.DesignError, match="canonical JSON"):
        audit.decode_evidence_index(json.dumps(document).encode())
    with pytest.raises(audit.DesignError, match="duplicate JSON"):
        audit.decode_evidence_index(b'{"entries":[],"entries":[]}')
