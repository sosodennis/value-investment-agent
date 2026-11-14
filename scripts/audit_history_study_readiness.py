"""Join frozen source/mapping diagnoses with explicitly replayed current evidence."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import subprocess
import tarfile
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Iterator

from analyze_history_study import hash_value, list_value, object_value, text_value
from audit_history_study_labels import audit_labels, decode_json, timestamp
from export_history_study_evidence import (
    EvidenceIndex,
    export_evidence,
    runtime_pins,
)
from plan_history_study_precision import (
    MANIFEST_DIGEST,
    ROOT,
    DesignError,
    canonical_bytes,
    digest,
    publish_report,
)

MARKER = "docs/acceptance/issue-361-marker62-evidence-v1"
READINESS = (
    "docs/acceptance/issue-361-cohort-root-evidence-v1/readiness/report/"
    "5defd97370924fd297d204cd66e2bc164c17ed1e0d2994a71c48d2f3c1aa30dd.json.gz"
)


@dataclass
class EvidenceArchive:
    archive: tarfile.TarFile
    members: dict[str, dict[str, object]]
    consumed: dict[str, str] = field(default_factory=dict)

    def document(self, path: str, expected: str | None = None) -> dict[str, object]:
        entry = self.members[path]
        handle = self.archive.extractfile(path)
        if handle is None:
            raise DesignError("archive evidence must be a regular file")
        with handle:
            packed = handle.read()
        if len(packed) != entry["byte_length"] or digest(packed) != entry["sha256"]:
            raise DesignError("archive member packed digest or length differs")
        raw = gzip.decompress(packed)
        content_digest = PurePosixPath(path).name.removesuffix(".json.gz")
        if digest(raw) != content_digest or (expected and expected != content_digest):
            raise DesignError("archive member content digest differs")
        result = object_value(decode_json(raw))
        if canonical_bytes(result) != raw:
            raise DesignError("archive evidence must be canonical JSON")
        self.consumed[path] = content_digest
        return result

    def reference(self, value: object) -> dict[str, object]:
        row = object_value(value)
        return self.document(text_value(row["path"]), hash_value(row["sha256"]))


@contextmanager
def open_archive(
    directory: Path, reference: dict[str, object]
) -> Iterator[EvidenceArchive]:
    manifest_raw = (
        directory / text_value(reference["archive_manifest_filename"])
    ).read_bytes()
    if digest(manifest_raw) != reference["archive_manifest_sha256"]:
        raise DesignError("archive manifest digest differs")
    manifest = object_value(decode_json(manifest_raw))
    path = directory / text_value(reference["archive_filename"])
    with path.open("rb") as handle:
        archive_digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if (
            path.stat().st_size != reference["archive_byte_length"]
            or archive_digest != reference["archive_sha256"]
            or manifest["archive_sha256"] != archive_digest
        ):
            raise DesignError("research archive digest or length differs")
        handle.seek(0)
        with tarfile.open(fileobj=handle, mode="r:gz") as archive:
            members = {}
            for value in list_value(manifest["files"]):
                row = object_value(value)
                name = text_value(row["path"])
                if name in members:
                    raise DesignError("duplicate archive manifest member")
                members[name] = row
            names = set()
            for member in archive.getmembers():
                name = member.name
                if (
                    not member.isfile()
                    or PurePosixPath(name).is_absolute()
                    or ".." in PurePosixPath(name).parts
                    or name in names
                    or name not in members
                    or member.size != members[name]["byte_length"]
                ):
                    raise DesignError("duplicate, unsafe or substituted archive member")
                names.add(name)
            if names != set(members) or len(names) != reference["file_count"]:
                raise DesignError("archive members differ from pinned manifest")
            yield EvidenceArchive(archive, members)


def target_key(row: dict[str, object]) -> tuple[str, str]:
    return text_value(row["issuer_id"]), text_value(row["accession"])


def source_records(
    archive: EvidenceArchive,
    checkpoint: dict[str, object],
    category: str,
    targets: dict[tuple[str, str], dict[str, object]],
) -> dict[tuple[str, str], dict[str, object]]:
    roots = object_value(object_value(checkpoint["inputs"])["roots"])
    records: dict[tuple[str, str], dict[str, object]] = {}
    for value in list_value(roots[category]):
        ref = object_value(value)
        if "/filings/" not in text_value(ref["path"]):
            continue
        row = archive.reference(ref)
        target = object_value(row["target"])
        key = target_key(target)
        if key in records or key not in targets or target != targets[key]:
            raise DesignError("duplicate or substituted source target")
        records[key] = {"reference": ref, "record": row}
    if set(records) != set(targets):
        raise DesignError("source diagnoses must retain every fixed filing target")
    return records


def mapping_records(
    archive: EvidenceArchive,
    issuer: dict[str, object],
    targets: dict[tuple[str, str], dict[str, object]],
) -> dict[str, dict[str, object]]:
    proposal = archive.reference(issuer["mapping_proposal"])
    packet = archive.reference(issuer["mapping_packet"])
    if (
        proposal["cik"] != text_value(issuer["issuer_id"])[4:]
        or proposal["decision_accession"] != issuer["decision_accession"]
        or proposal["decision_at"] != issuer["decision_at"]
        or proposal["input_issuer_digest"]
        != object_value(issuer["mapping_packet"])["sha256"]
        or packet["cik"] != proposal["cik"]
        or packet["decision_accession"] != proposal["decision_accession"]
        or packet["decision_at"] != proposal["decision_at"]
    ):
        raise DesignError("mapping issuer, origin or packet identity differs")
    fields = {}
    for value in list_value(packet["field_rows"]):
        row = object_value(value)
        key = text_value(row["accession"]), text_value(row["field"])
        if key in fields:
            raise DesignError("duplicate mapping packet field")
        fields[key] = row
    seen = set()
    grouped: dict[str, list[dict[str, object]]] = {}
    for value in list_value(proposal["mapping_decisions"]):
        row = object_value(value)
        key = text_value(row["accession"]), text_value(row["field"])
        target = targets.get((text_value(issuer["issuer_id"]), key[0]))
        source = fields.get(key)
        if key in seen or target is None or source is None:
            raise DesignError("duplicate or substituted mapping decision")
        if any(
            row[name] != expected or source[name] != expected
            for name, expected in {
                "period_end": target["period_end"],
                "available_at": target["accepted_at"],
                "amendment": target["form"] == "10-K/A",
                "role": "label" if target["role"] == "label" else "history",
            }.items()
        ):
            raise DesignError("mapping period, availability, amendment or role differs")
        seen.add(key)
        grouped.setdefault(key[0], []).append(row)
    if seen != set(fields):
        raise DesignError("mapping proposal omits packet fields")
    required = {accession for cik, accession in targets if cik == issuer["issuer_id"]}
    if set(grouped) != required:
        raise DesignError("mapping must retain every issuer filing target")
    return {
        accession: {
            "authority": "archived_companyfacts_proposals_not_original_disclosure_adjudication",
            "packet_reference": issuer["mapping_packet"],
            "proposal_reference": issuer["mapping_proposal"],
            "fields": [
                {
                    name: row[name]
                    for name in (
                        "field",
                        "decision_id",
                        "disposition",
                        "missing_reason",
                        "value_conflict",
                        "candidate_fact_ids",
                        "rejected_candidate_ids",
                        "mapping_version",
                    )
                }
                for row in sorted(rows, key=lambda row: text_value(row["field"]))
            ],
            "disposition_counts": dict(
                sorted(Counter(text_value(row["disposition"]) for row in rows).items())
            ),
        }
        for accession, rows in grouped.items()
    }


def audit_readiness(
    manifest: object,
    snapshots: Path,
    archive: EvidenceArchive,
    conditional: dict[str, object],
) -> dict[str, object]:
    labels = audit_labels(manifest, snapshots)
    frozen = object_value(manifest)
    inventory = object_value(frozen["original_inventory"])
    targets = {}
    for value in list_value(inventory["targets"]):
        target = object_value(value)
        key = target_key(target)
        if key in targets:
            raise DesignError("duplicate fixed filing target")
        targets[key] = target
    if len(targets) != 589:
        raise DesignError("all 589 fixed filing targets are required")
    checkpoint = archive.document(
        f"{MARKER}/checkpoint/{hash_value(frozen['source_checkpoint_digest'])}.json.gz"
    )
    diagnoses = source_records(
        archive, checkpoint, "integrity_source_observations", targets
    )
    lexical = source_records(archive, checkpoint, "legacy_concept_discovery", targets)
    expected_results = {
        hash_value(object_value(v)["sha256"])
        for v in list_value(frozen["original_filing_outcome_refs"])
    }
    root_refs = list_value(
        object_value(object_value(checkpoint["inputs"])["roots"])["originals"]
    )
    retained_results = {
        hash_value(object_value(v)["sha256"])
        for v in root_refs
        if text_value(object_value(v)["original_path"]).startswith("results/")
    }
    if retained_results != expected_results or len(retained_results) != len(targets):
        raise DesignError("retained outcome references differ from fixed manifest")
    # Integrity/lexical observations used an earlier execution; target equality
    # links the filing, never upgrades their result digest to the newer run.
    old = archive.document(READINESS)
    old_issuers = {}
    for value in list_value(object_value(old["output"])["issuers"]):
        row = object_value(value)
        issuer = text_value(row["issuer_id"])
        if issuer in old_issuers:
            raise DesignError("duplicate archived issuer")
        old_issuers[issuer] = row
    current: dict[str, list[object]] = {}
    for value in list_value(conditional["arm_summaries"]):
        row = object_value(value)
        current.setdefault(text_value(row["issuer_id"]), []).append(row)
    rows = []
    mapping_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    integrity_counts: Counter[str] = Counter()
    no_failure_code = 0
    label_rows = [object_value(v) for v in list_value(labels["rows"])]
    if set(old_issuers) != {text_value(v["issuer_id"]) for v in label_rows} or not set(
        current
    ) <= set(old_issuers):
        raise DesignError("archived or conditional evidence substitutes fixed issuers")
    for label in label_rows:
        issuer = text_value(label["issuer_id"])
        old_issuer = old_issuers[issuer]
        decision = object_value(label["decision"])
        if old_issuer["decision_accession"] != decision["accession"] or timestamp(
            old_issuer["decision_at"]
        ) != timestamp(decision["accepted_at"]):
            raise DesignError("archived decision differs from frozen origin")
        mappings = mapping_records(archive, old_issuer, targets)
        annual = []
        for key, target in sorted(targets.items()):
            if key[0] != issuer:
                continue
            diagnosis = object_value(diagnoses[key]["record"])
            discovery = object_value(lexical[key]["record"])
            if diagnosis["frozen_result_digest"] != discovery["frozen_result_digest"]:
                raise DesignError("source diagnostic references conflicting outcomes")
            if target["role"] != "label" and timestamp(
                target["accepted_at"]
            ) > timestamp(decision["accepted_at"]):
                raise DesignError("future filing cannot enter decision history")
            mapping = mappings[key[1]]
            mapping_counts.update(
                text_value(object_value(v)["disposition"])
                for v in list_value(mapping["fields"])
            )
            if diagnosis["frozen_code"] is None:
                no_failure_code += 1
            else:
                status_counts[text_value(diagnosis["frozen_code"])] += 1
            integrity_counts[text_value(diagnosis["status"])] += 1
            annual.append(
                {
                    "target": target,
                    "archived_source": diagnoses[key],
                    "archived_lexical_reference": lexical[key]["reference"],
                    "archived_lexical_status": discovery["discovery_status"],
                    "archived_legacy_result_digest": diagnosis["frozen_result_digest"],
                    "current_parser_validation": "not_reexecuted_by_readiness_audit",
                    "archived_mapping": mapping,
                }
            )
        rows.append(
            {
                "issuer_id": issuer,
                "decision": decision,
                "label_audit": label,
                "filing_targets": annual,
                "available_original_period_ends": sorted(
                    {
                        text_value(object_value(r["target"])["period_end"])
                        for r in annual
                        if object_value(r["target"])["form"] == "10-K"
                        and object_value(r["target"])["role"] != "label"
                    }
                ),
                "current_conditional_arms": current.get(issuer, []),
                "current_evidence_status": (
                    "provisional_conditional"
                    if any(
                        object_value(v)["conditional_comparisons"] != 0
                        for v in current.get(issuer, [])
                    )
                    else "abstained_conditional"
                    if issuer in current
                    else "not_supplied_in_explicit_evidence_index"
                ),
                "exact_study_case": False,
                "next_required_evidence": [
                    "original_period_semantic_mapping_adjudication",
                    "authenticated_exact_release_and_label",
                    "reviewed_method_and_promotion_policy",
                ],
            }
        )
    return {
        "schema_version": "history-study-readiness-audit.v1",
        "authority": "archived_diagnoses_plus_recomputed_conditional_arithmetic_not_trusted_release",
        "fixed_manifest_digest": MANIFEST_DIGEST,
        "selected_issuers": len(rows),
        "filing_targets": len(targets),
        "label_disposition_counts": labels["disposition_counts"],
        "maximum_eligible_label_pairs": labels["maximum_eligible_label_pairs"],
        "archived_source_failure_code_counts": dict(sorted(status_counts.items())),
        "archived_source_no_failure_code_count": no_failure_code,
        "archived_source_integrity_status_counts": dict(
            sorted(integrity_counts.items())
        ),
        "archived_mapping_disposition_counts": dict(sorted(mapping_counts.items())),
        "fixed_original_reference_commit": object_value(checkpoint["inputs"])[
            "source_commit"
        ],
        "archived_diagnosis_authority": "earlier_legacy_execution_linked_by_exact_target_not_result_identity",
        "archived_mapping_commit": object_value(old["inputs"])["source_commit"],
        "current_conditional_evidence": conditional,
        "complete_exact_study_cases": 0,
        "verified_issuers": 0,
        "independent_conditional_issuers": conditional[
            "independent_conditional_issuers"
        ],
        "source_completeness_verified": False,
        "mapping_or_release_approved": False,
        "threshold_decision": "underpowered_no_exact_release_bound_losses",
        "supported_history_threshold": None,
        "rows": rows,
    }


def decode_evidence_index(raw: bytes) -> EvidenceIndex:
    document = decode_json(raw)
    if canonical_bytes(document) != raw:
        raise DesignError("evidence index must be canonical JSON")
    # Strict Pydantic accepts JSON arrays for tuple fields only at its JSON boundary.
    return EvidenceIndex.model_validate_json(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "manifest",
        "snapshot-directory",
        "archive-directory",
        "evidence-index",
        "output-directory",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--exact-commit", required=True)
    args = parser.parse_args()
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        if head != args.exact_commit or subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True
        ):
            raise DesignError("exact clean implementation commit is required")
        manifest_raw = args.manifest.read_bytes()
        manifest = decode_json(manifest_raw)
        if canonical_bytes(manifest) != manifest_raw:
            raise DesignError("fixed manifest must be canonical JSON")
        index_raw = args.evidence_index.read_bytes()
        index = decode_evidence_index(index_raw)
        conditional = export_evidence(manifest, index, args.evidence_index.parent)
        reference_path = ROOT / "docs/acceptance/issue-361-research-archive.json"
        reference = object_value(decode_json(reference_path.read_bytes()))
        with open_archive(args.archive_directory, reference) as archive:
            output = audit_readiness(
                manifest, args.snapshot_directory, archive, conditional
            )
            consumed = dict(sorted(archive.consumed.items()))
        methods = {
            name: digest((ROOT / "docs/research" / name).read_bytes())
            for name in (
                "issue-377-methods-v4.json",
                "issue-377-protocol-proposal-v3.json",
            )
        }
        inputs = {
            "issue": 376,
            "exact_commit": head,
            "fixed_manifest_digest": MANIFEST_DIGEST,
            "manifest_bytes_digest": digest(manifest_raw),
            "archive_reference_digest": digest(reference_path.read_bytes()),
            "archive_digest": reference["archive_sha256"],
            "archive_manifest_digest": reference["archive_manifest_sha256"],
            "consumed_archive_members": consumed,
            "evidence_index_digest": digest(index_raw),
            "runtime": runtime_pins().model_dump(mode="json"),
            "methods_review_candidates": methods,
            "tool_digests": {
                name: digest((ROOT / "scripts" / name).read_bytes())
                for name in (
                    Path(__file__).name,
                    "audit_history_study_labels.py",
                    "export_history_study_evidence.py",
                    "analyze_history_study.py",
                    "plan_history_study_precision.py",
                )
            },
        }
        output["methods_review"] = {
            "candidate_file_digests": methods,
            "status": "frozen_candidates_pending_independent_review_not_approved",
            "known_outcome_inspection": "NEWMARKET_conditional_pilot_seen_before_methods_v4",
            "promotion_enabled": False,
            "legacy_complete_pair_gate_changed": False,
        }
        report = {
            "inputs": inputs,
            "input_digest": digest(canonical_bytes(inputs)),
            "output": output,
            "output_digest": digest(canonical_bytes(output)),
        }
        result = publish_report(args.output_directory, report)
        print(
            json.dumps(
                {
                    **result,
                    "input_digest": report["input_digest"],
                    "output_digest": report["output_digest"],
                },
                sort_keys=True,
            )
        )
    except (
        OSError,
        ValueError,
        KeyError,
        EOFError,
        tarfile.TarError,
        subprocess.CalledProcessError,
    ) as error:
        parser.exit(2, f"history-study readiness audit failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
