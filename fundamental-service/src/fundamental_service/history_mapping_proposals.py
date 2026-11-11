"""Author explicit issuer-period mapping proposals without approving them."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

from .facts import CanonicalMappingV1
from .history_mapping_audit import (
    DEFAULT_COHORT_MANIFEST,
    ROOT,
    MappingAuditError,
    _array,
    _object,
    _read_json,
    _selected_issuers,
    _text,
)
from .history_replay import (
    _ensure_tracked_tree_clean,
    _resolve_commit,
    _runtime_pins,
    _write_content_addressed,
)
from .history_replay_inputs import DEFAULT_DIRECTORY, _digest
from .serialization import sha256_digest

MAPPING_VERSION = "sec-fcff-issuer-period-proposals-v1"
AUTHOR_ID = "codex/issue-361-replay-evidence"


def _read_artifact(path: Path, expected_digest: str) -> dict[str, object]:
    content = gzip.decompress(path.read_bytes())
    if _digest(content) != expected_digest:
        raise MappingAuditError("mapping proposal input digest mismatch")
    result = _object(json.loads(content), "mapping artifact")
    if sha256_digest(result) != expected_digest:
        raise MappingAuditError("mapping proposal input is not canonical")
    return result


def propose_field_mapping(
    field_row: dict[str, object], *, cik: str, source_hash: str
) -> dict[str, object]:
    """Propose a unique source identity; competing meanings require adjudication."""

    candidates = [
        _object(row, "candidate")
        for row in _array(field_row.get("candidate_facts"), "candidates")
    ]
    eligible = [row for row in candidates if not row["rejection_reasons"]]
    signatures = {
        (
            row["concept"],
            row["period_start"],
            row["period_end"],
            row["unit"],
            row["value"],
        )
        for row in eligible
    }
    if any(row.get("source_response_hash") != source_hash for row in candidates):
        raise MappingAuditError("mapping candidate source hash mismatch")
    if any(row.get("accession") != field_row["accession"] for row in candidates):
        raise MappingAuditError("mapping candidate accession mismatch")
    selected = (
        min(eligible, key=lambda row: str(row["candidate_fact_id"]))
        if len(signatures) == 1
        else None
    )
    disposition = (
        "proposed_exact_candidate_requires_review"
        if selected is not None
        else "unresolved_no_eligible_candidate"
        if not eligible
        else "unresolved_competing_candidates"
    )
    identity = {
        "cik": cik,
        "role": field_row["role"],
        "accession": field_row["accession"],
        "period_end": field_row["period_end"],
        "field": field_row["field"],
        "source_hash": source_hash,
        "mapping_version": MAPPING_VERSION,
        "candidate_fact_ids": sorted(str(row["candidate_fact_id"]) for row in eligible),
        "disposition": disposition,
    }
    decision_id = sha256_digest(identity)
    preview = None
    if selected is not None:
        preview = CanonicalMappingV1(
            contract_version="fundamental.v1",
            decision_id=decision_id,
            source_concept=str(selected["concept"]),
            normalized_field=str(field_row["field"]),
            mapping_version=MAPPING_VERSION,
            confidence="medium",
            evidence_refs=(source_hash, str(selected["candidate_fact_id"])),
            reviewer=None,
            reviewed_at=None,
            status="provisional",
        ).model_dump(mode="json")
    return {
        **identity,
        "decision_id": decision_id,
        "author_id": AUTHOR_ID,
        "reviewer_id": None,
        "review_signature": None,
        "available_at": field_row["available_at"],
        "amendment": field_row["amendment"],
        "value_conflict": field_row["value_conflict"],
        "missing_reason": field_row["missing_reason"],
        "selected_candidate": selected,
        "canonical_mapping_preview": preview,
        "rejected_candidate_ids": sorted(
            str(row["candidate_fact_id"])
            for row in candidates
            if row["rejection_reasons"]
        ),
        "review_checks": [
            "Confirm issuer consolidated scope, security class, unit, period and sign in source disclosure.",
            "Confirm the source concept covers the entire normalized role; a unique value does not prove semantic equivalence.",
            "Do not map legacy operating lease commitments to recognized lease liabilities or fill missing disclosure with zero.",
            "For labels use only the first subsequent original annual accession; later comparative restatements remain excluded.",
        ],
    }


def build_mapping_proposals(*, review_manifest_path: Path) -> dict[str, object]:
    digest = review_manifest_path.name.removesuffix(".json.gz")
    manifest = _read_artifact(review_manifest_path, digest)
    if manifest.get("cohort_digest") != _digest(DEFAULT_COHORT_MANIFEST.read_bytes()):
        raise MappingAuditError("mapping proposals differ from the fixed cohort")
    refs = [
        _object(row, "issuer reference")
        for row in _array(manifest.get("issuer_refs"), "issuer references")
    ]
    selected = _selected_issuers(_read_json(DEFAULT_COHORT_MANIFEST, "fixed cohort"))
    if len(refs) != len(selected) or {row["cik"] for row in refs} != {
        row["cik"] for row in selected
    }:
        raise MappingAuditError(
            "mapping proposals changed the fixed issuer denominator"
        )
    issuer_rows = []
    dispositions: Counter[str] = Counter()
    for ref in refs:
        issuer_digest = _text(ref.get("sha256"), "issuer digest")
        if len(issuer_digest) != 64 or any(
            char not in "0123456789abcdef" for char in issuer_digest
        ):
            raise MappingAuditError("invalid issuer artifact digest")
        issuer = _read_artifact(
            review_manifest_path.parents[1]
            / "mapping_issuers"
            / f"{issuer_digest}.json.gz",
            issuer_digest,
        )
        if issuer.get("cik") != ref["cik"]:
            raise MappingAuditError("mapping proposal issuer identity mismatch")
        source = _object(issuer.get("source_record"), "source")
        decisions = [
            propose_field_mapping(
                _object(row, "field"),
                cik=str(ref["cik"]),
                source_hash=str(source["response_sha256"]),
            )
            for row in _array(issuer.get("field_rows"), "field rows")
        ]
        dispositions.update(str(row["disposition"]) for row in decisions)
        issuer_rows.append(
            {
                "cik": issuer["cik"],
                "decision_accession": issuer["decision_accession"],
                "decision_at": issuer["decision_at"],
                "first_subsequent_original_accession": issuer[
                    "first_subsequent_original_accession"
                ],
                "label_status": issuer["label_status"],
                "input_issuer_digest": issuer_digest,
                "source_record": source,
                "mapping_decisions": decisions,
            }
        )
    return {
        "schema_version": "sec-issuer-period-mapping-proposals-v1",
        "mapping_version": MAPPING_VERSION,
        "author_id": AUTHOR_ID,
        "reviewer_id": None,
        "review_signature": None,
        "runtime": _runtime_pins(_resolve_commit()),
        "input_digest": digest,
        "source_manifest_digest": manifest["source_manifest_digest"],
        "cohort_digest": manifest["cohort_digest"],
        "selected_issuer_count": len(issuer_rows),
        "dispositions": dict(sorted(dispositions.items())),
        "approved_mapping_count": 0,
        "canonical_fact_count": 0,
        "supported_history_threshold": None,
        "issuer_rows": sorted(
            issuer_rows, key=lambda row: (str(row["decision_at"]), str(row["cik"]))
        ),
    }


def write_mapping_proposals(
    package: dict[str, object], output_directory: Path
) -> dict[str, object]:
    refs = []
    artifacts = []
    for value in _array(package["issuer_rows"], "issuers"):
        issuer = _object(value, "issuer")
        artifact = _write_content_addressed(
            output_directory, "proposed_mapping_issuers", issuer
        )
        artifacts.append(artifact)
        refs.append({"cik": issuer["cik"], "sha256": artifact["sha256"]})
    manifest = {key: value for key, value in package.items() if key != "issuer_rows"}
    manifest["issuer_refs"] = refs
    artifact = _write_content_addressed(output_directory, "mapping_proposals", manifest)
    return {
        "input_digest": package["input_digest"],
        "output_digest": artifact["sha256"],
        "manifest": artifact,
        "issuer_artifacts": artifacts,
        "wrote": artifact["wrote"] or any(row["wrote"] for row in artifacts),
    }


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-manifest", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_DIRECTORY)
    args = parser.parse_args(argv)
    try:
        _ensure_tracked_tree_clean(str(Path(__file__).resolve().relative_to(ROOT)))
        package = build_mapping_proposals(review_manifest_path=args.review_manifest)
        result = write_mapping_proposals(package, args.output_directory)
        print(
            json.dumps(
                {"commit_sha": _resolve_commit(), "command_result": "exit 0", **result},
                sort_keys=True,
            )
        )
        return 0
    except (OSError, ValueError) as error:
        print(f"mapping proposal failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(_main())
