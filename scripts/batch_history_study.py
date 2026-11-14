"""Replay fixed original evidence into source-bound review packets and study arms."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import Field

from fundamental_service.arelle_parser import ArelleParseReportV1
from fundamental_service.automatic_mapping import (
    AUTOMATIC_MAPPING_POLICY,
    automatic_mapping_policy_digest,
    automatic_mapping_proposals,
)
from fundamental_service.contracts import StrictModel
from fundamental_service.operating_label_contracts import OperatingComparisonRequestV1
from fundamental_service.operating_scenario_policy import CORE_FIELDS, PARENT_CONCEPTS
from fundamental_service.original_issuer import (
    OriginalIssuerEvidenceV1,
    OriginalOperatingSourceV1,
    evaluate_original_issuer,
)
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError

from analyze_history_study import (
    MODELS,
    WINDOWS,
    list_value,
    object_value,
    text_value,
)
from audit_history_study_labels import timestamp
from export_history_study_evidence import (
    FileReference,
    RuntimePins,
    read_evidence,
    runtime_pins,
)
from plan_history_study_precision import (
    MANIFEST_DIGEST,
    ROOT,
    DesignError,
    digest,
    publish_report,
)
from read_history_originals import (
    PARSER_EXECUTION,
    SOURCE_REVISION,
    OriginalReader,
    checked_document,
)
from replay_history_study_windows import WindowSeedIndex, prepare_windows

PROTOCOL = "fixed100-original-candidate-batch-v1"
MAPPING_VERSION = "fixed100-original-review-proposals-v1"


class BatchIndex(StrictModel):
    schema_version: Literal["history-study-batch-index.v1"]
    fixed_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_revision: Literal["32be2dafbbc7756bf185e228dc8fdcc280fe6cf3"] = (
        SOURCE_REVISION
    )
    runtime: RuntimePins
    originals: tuple[FileReference, ...] = ()
    seeds: tuple[FileReference, ...] = Field(default=(), max_length=100)


def target_key(row: dict[str, object]) -> tuple[str, str]:
    return text_value(row["issuer_id"]), text_value(row["accession"])


def fixed_targets(
    manifest: object,
) -> tuple[list[dict[str, object]], dict[tuple[str, str], dict[str, object]]]:
    if sha256_digest(manifest) != MANIFEST_DIGEST:
        raise DesignError("fixed 100-issuer manifest digest differs")
    frozen = object_value(manifest)
    issuers = [object_value(v) for v in list_value(frozen["issuer_decisions"])]
    targets = [
        object_value(v)
        for v in list_value(object_value(frozen["original_inventory"])["targets"])
    ]
    by_key = {target_key(row): row for row in targets}
    issuer_ids = {text_value(row["issuer_id"]) for row in issuers}
    if (
        len(issuers) != 100
        or len(issuer_ids) != 100
        or len(targets) != 589
        or len(by_key) != 589
    ):
        raise DesignError("all fixed 100 issuers and 589 unique targets are required")
    if {key[0] for key in by_key} != issuer_ids:
        raise DesignError("fixed issuer/target set differs")
    decisions = {text_value(row["issuer_id"]): row for row in issuers}
    for target in targets:
        issuer = decisions[text_value(target["issuer_id"])]
        accepted = timestamp(target["accepted_at"])
        expected_at = (
            issuer["decision_at"]
            if target["role"] != "label"
            else target["accepted_at"]
        )
        if target["valuation_timestamp"] != expected_at or accepted > timestamp(
            expected_at
        ):
            raise DesignError("future or substituted original valuation timestamp")
        if target["role"] == "label":
            if target["accession"] != issuer[
                "label_accession"
            ] or accepted <= timestamp(issuer["decision_at"]):
                raise DesignError("substituted or nonfuture frozen label")
        elif (
            target["role"] == "decision"
            and target["accession"] != issuer["decision_accession"]
        ):
            raise DesignError("substituted decision accession")
        elif target["role"] not in ("decision", "history"):
            raise DesignError("unknown fixed original role")
    return sorted(issuers, key=lambda row: text_value(row["issuer_id"])), by_key


def original_from_record(
    record: dict[str, object], target: dict[str, object]
) -> OriginalIssuerEvidenceV1 | None:
    inputs, output = object_value(record["inputs"]), object_value(record["output"])
    if (
        inputs["target"] != target
        or object_value(inputs["pins"])["source_commit"] != PARSER_EXECUTION
        or record["input_digest"] != sha256_digest(inputs)
        or record["output_digest"] != sha256_digest(output)
        or output["canonical_release_published"] is not False
        or output["canonical_snapshot_published"] is not False
    ):
        raise DesignError("original result target, execution or envelope differs")
    if output["status"] == "refused":
        text_value(output["code"])
        return None
    if output["status"] != "validation_passed_unpublished":
        raise DesignError("unknown retained original outcome")
    integrity = object_value(output["integrity_evidence"])
    sources = [object_value(v) for v in list_value(output["sources"])]
    matches = [
        row for row in sources if row["uri"] == integrity["primary_document_uri"]
    ]
    if len(matches) != 1:
        raise DesignError("original primary source is missing or ambiguous")
    primary = matches[0]
    if (
        primary["accession"] != target["accession"]
        or integrity["accession_number"] != target["accession"]
        or primary["available_at"] != target["accepted_at"]
        or primary["form"] != target["form"]
        or primary["content_hash"] != integrity["raw_content_hash"]
    ):
        raise DesignError("original source metadata differs from fixed target")
    source = OriginalOperatingSourceV1.model_validate_json(
        canonical_bytes(
            {
                "cik": target["cik"],
                "accession_number": target["accession"],
                "uri": primary["uri"],
                "content_hash": primary["content_hash"],
                "parser_input_hash": integrity["parser_input_hash"],
                "form": target["form"],
                "is_amendment": target["form"] == "10-K/A",
                "available_at": target["accepted_at"],
                "captured_at": integrity["captured_at"],
            }
        )
    )
    report = ArelleParseReportV1.model_validate_json(
        canonical_bytes(
            {
                **object_value(output["parser_report"]),
                "filing_path": source.uri,
                "parsed_at": integrity["captured_at"],
            }
        )
    )
    if report.replay_digest() != output["parser_digest"]:
        raise DesignError("retained parser replay digest differs")
    return evaluate_original_issuer(
        report, source=source, decision_at=timestamp(target["valuation_timestamp"])
    )


def check_original(
    original: OriginalIssuerEvidenceV1, target: dict[str, object]
) -> None:
    source = original.source
    if (
        source.cik != target["cik"]
        or source.accession_number != target["accession"]
        or source.form != target["form"]
        or source.is_amendment != (target["form"] == "10-K/A")
        or source.available_at != timestamp(target["accepted_at"])
        or original.decision_at != timestamp(target["valuation_timestamp"])
        or (
            original.report_period_end is not None
            and original.report_period_end.isoformat() != target["period_end"]
        )
    ):
        raise DesignError(
            "supplemental original issuer, accession, period or availability differs"
        )


def candidate_packet(original: OriginalIssuerEvidenceV1) -> dict[str, object]:
    """Retain observations for review; never infer complete accounting scope."""
    rows = []
    for name in (*CORE_FIELDS, *PARENT_CONCEPTS):
        proposals = automatic_mapping_proposals(
            name, mapping_version=MAPPING_VERSION, original=original
        )
        candidates = {}
        codes = set(original.issue_codes)
        if original.status != "matched":
            codes.add("ORIGINAL_ISSUER_REFUSED")
        elif original.report.blocking_finding_codes():
            codes.add("PARSER_VALIDATION_BLOCKED")
        else:
            for proposal in proposals:
                try:
                    observations = parsed_facts_to_candidates(
                        original.report,
                        source=original.source,
                        issuer_id=original.source.cik,
                        normalized_field=name,
                        mapping=proposal,
                    )
                except SnapshotError as error:
                    codes.add(error.code)
                    continue
                for candidate in observations:
                    candidates[candidate.candidate_id] = candidate
        if not proposals:
            codes.add("NO_EXECUTABLE_MAPPING_PROPOSAL")
        if not candidates:
            codes.add("NO_SOURCE_BOUND_CANDIDATE_IN_SUPPLIED_REPORT")
        rows.append(
            {
                "field": name,
                "proposals": proposals,
                "candidates": [candidates[key] for key in sorted(candidates)],
                "candidate_count": len(candidates),
                "issue_codes": sorted(codes),
                "status": "requires_semantic_review" if candidates else "unresolved",
            }
        )
    return {
        "original_evidence_digest": sha256_digest(original),
        "parser_replay_digest": original.report.replay_digest(),
        "parser_blocking_codes": original.report.blocking_finding_codes(),
        "original_issue_codes": original.issue_codes,
        "fields": rows,
        "authority": "provisional_candidates_not_approved_mapping_or_model_inputs",
    }


def load_supplements(
    index: BatchIndex,
    directory: Path,
    targets: dict[tuple[str, str], dict[str, object]],
) -> tuple[
    dict[tuple[str, str], tuple[FileReference, OriginalIssuerEvidenceV1]],
    dict[str, FileReference],
]:
    originals = {}
    for ref in index.originals:
        original = OriginalIssuerEvidenceV1.model_validate_json(
            read_evidence(ref, directory)
        )
        key = f"CIK:{original.source.cik}", original.source.accession_number
        if key in originals or key not in targets:
            raise DesignError("duplicate or substituted supplemental original")
        check_original(original, targets[key])
        originals[key] = ref, original
    seeds = {}
    for ref in index.seeds:
        request = OperatingComparisonRequestV1.model_validate_json(
            read_evidence(ref, directory)
        )
        issuer = f"CIK:{request.decision.source.identity.issuer_id}"
        if issuer in seeds or not any(key[0] == issuer for key in targets):
            raise DesignError("duplicate or substituted batch seed issuer")
        seeds[issuer] = ref
    return originals, seeds


def prepare_batch(
    manifest: object,
    index: BatchIndex,
    directory: Path,
    reader: OriginalReader,
    *,
    exact_commit: str,
    limit: int = 100,
) -> tuple[dict[str, object], dict[str, bytes]]:
    issuers, targets = fixed_targets(manifest)
    if limit not in (10, 100):
        raise DesignError("only canonical first10 or full100 batches are supported")
    if (
        index.fixed_manifest_digest != MANIFEST_DIGEST
        or index.runtime != runtime_pins()
    ):
        raise DesignError("batch manifest or installed runtime differs from pins")
    originals, seeds = load_supplements(index, directory, targets)
    records = {}
    for value in list_value(object_value(manifest)["original_filing_outcome_refs"]):
        ref = object_value(value)
        record = reader.document(ref)
        key = target_key(object_value(object_value(record["inputs"])["target"]))
        if key in records or key not in targets:
            raise DesignError("duplicate or substituted retained original result")
        original = original_from_record(record, targets[key])
        records[key] = ref, record, original
    if set(records) != set(targets):
        raise DesignError("retained original outcomes must cover every fixed target")
    pins = {
        "exact_commit": exact_commit,
        "protocol": PROTOCOL,
        "fixed_manifest_digest": MANIFEST_DIGEST,
        "runtime": index.runtime,
        "source_revision": reader.revision,
        "retained_parser_execution": PARSER_EXECUTION,
        "mapping_version": MAPPING_VERSION,
        "mapping_policy_version": AUTOMATIC_MAPPING_POLICY,
        "mapping_policy_digest": automatic_mapping_policy_digest(),
    }
    artifacts: dict[str, bytes] = {}

    def retain(value: object) -> str:
        raw = canonical_bytes(value)
        identity = digest(raw)
        artifacts[identity] = raw
        return identity

    summaries = []
    for issuer in issuers[:limit]:
        issuer_id = text_value(issuer["issuer_id"])
        filings = []
        for key, target in sorted(
            targets.items(), key=lambda item: (item[1]["accepted_at"], item[0])
        ):
            if key[0] != issuer_id:
                continue
            ref, record, archived = records[key]
            original = originals[key][1] if key in originals else archived
            output = object_value(record["output"])
            entry: dict[str, object] = {
                "target": target,
                "retained_result_digest": ref["sha256"],
                "retained_status": output["status"],
                "retained_failure_code": output.get("code"),
                "retained_output_digest": record["output_digest"],
                "supplemental_original_digest": originals[key][0].sha256
                if key in originals
                else None,
                "source_evidence_digest": retain(original)
                if original is not None
                else None,
                "candidate_packet_digest": None,
                "candidate_count": 0,
                "status": "retained_source_refusal",
                "issue_codes": [output["code"]] if output.get("code") else [],
            }
            if original is not None:
                check_original(original, target)
                packet = candidate_packet(original)
                entry.update(
                    {
                        "candidate_packet_digest": retain(packet),
                        "candidate_count": sum(
                            int(str(object_value(row)["candidate_count"]))
                            for row in list_value(packet["fields"])
                        ),
                        "status": "original_issuer_refused"
                        if original.status != "matched"
                        else "retained_parser_blocked"
                        if original.report.blocking_finding_codes()
                        else "unreviewed_candidate_packet",
                        "issue_codes": sorted(
                            set(original.issue_codes)
                            | set(original.report.blocking_finding_codes())
                        ),
                    }
                )
            filings.append(entry)
        seed = seeds.get(issuer_id)
        replay = None
        if seed is not None:
            replay, generated = prepare_windows(
                manifest,
                WindowSeedIndex(
                    schema_version="history-study-window-seeds.v1",
                    fixed_manifest_digest=MANIFEST_DIGEST,
                    runtime=index.runtime,
                    seeds=(seed,),
                ),
                directory,
            )
            artifacts.update(generated)
            retain(replay["evidence_index"])
        arms = (
            [
                {
                    "model_id": model,
                    "years": years,
                    "status": "abstain",
                    "issue_codes": ["CURRENT_REPLAY_SEED_NOT_SUPPLIED"],
                    "quality_status": "abstain",
                }
                for model in MODELS
                for years in WINDOWS
            ]
            if replay is None
            else replay["arm_summaries"]
        )
        packet = {
            "inputs": {
                **pins,
                "issuer": issuer,
                "seed_digest": seed.sha256 if seed else None,
                "retained_result_digests": [
                    row["retained_result_digest"] for row in filings
                ],
                "supplemental_original_digests": [
                    row["supplemental_original_digest"] for row in filings
                ],
            },
            "output": {
                "filings": filings,
                "arms": arms,
                "replay": replay,
                "exact_completed_cases": 0,
                "supported_history_threshold": None,
            },
        }
        packet["input_digest"] = sha256_digest(packet["inputs"])
        packet["output_digest"] = sha256_digest(packet["output"])
        summaries.append(
            {
                "issuer_id": issuer_id,
                "packet_digest": retain(packet),
                "filing_count": len(filings),
                "candidate_count": sum(
                    int(str(row["candidate_count"])) for row in filings
                ),
                "retained_failure_counts": dict(
                    sorted(
                        Counter(
                            text_value(row["retained_failure_code"])
                            for row in filings
                            if row["retained_failure_code"]
                        ).items()
                    )
                ),
                "independent_conditional_case": replay is not None
                and replay["independent_conditional_issuers"] == 1,
            }
        )
    return {
        "schema_version": "history-study-batch-output.v1",
        "protocol": PROTOCOL,
        "fixed_issuer_count": 100,
        "processed_issuer_count": len(summaries),
        "unprocessed_issuers": [row["issuer_id"] for row in issuers[limit:]],
        "processed_filing_count": sum(
            int(str(row["filing_count"])) for row in summaries
        ),
        "source_bound_candidate_count": sum(
            int(str(row["candidate_count"])) for row in summaries
        ),
        "independent_conditional_issuers": sum(
            row["independent_conditional_case"] is True for row in summaries
        ),
        "complete_exact_study_cases": 0,
        "verified_issuers": 0,
        "supported_history_threshold": None,
        "issuers": summaries,
        "authority": "retained_original_replay_and_unreviewed_candidates_not_trusted_releases",
    }, artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "index", "source-repository", "output-directory"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--exact-commit", required=True)
    parser.add_argument("--limit", type=int, choices=(10, 100), default=100)
    args = parser.parse_args()
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        if head != args.exact_commit or subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True
        ):
            raise DesignError("exact clean implementation commit is required")
        manifest = checked_document(args.manifest.read_bytes(), MANIFEST_DIGEST)
        index_raw = args.index.read_bytes()
        checked_document(index_raw, digest(index_raw))
        index = BatchIndex.model_validate_json(index_raw)
        output, artifacts = prepare_batch(
            manifest,
            index,
            args.index.parent,
            OriginalReader(args.source_repository),
            exact_commit=head,
            limit=args.limit,
        )
        inputs = {
            "issue": 376,
            "exact_commit": head,
            "protocol": PROTOCOL,
            "manifest_digest": MANIFEST_DIGEST,
            "index_digest": digest(index_raw),
            "runtime": index.runtime,
            "limit": args.limit,
        }
        report = {
            "inputs": inputs,
            "input_digest": sha256_digest(inputs),
            "output": output,
            "output_digest": sha256_digest(output),
        }
        receipts = [
            publish_report(args.output_directory, json.loads(raw))
            for _, raw in sorted(artifacts.items())
        ]
        receipt = publish_report(
            args.output_directory, json.loads(canonical_bytes(report))
        )
        print(
            json.dumps(
                {
                    **receipt,
                    "wrote": receipt["wrote"] or any(row["wrote"] for row in receipts),
                    "artifacts_written": sum(row["wrote"] is True for row in receipts)
                    + int(receipt["wrote"] is True),
                    "input_digest": report["input_digest"],
                    "output_digest": report["output_digest"],
                    "processed_issuers": output["processed_issuer_count"],
                },
                sort_keys=True,
            )
        )
    except (
        OSError,
        ValueError,
        ArithmeticError,
        subprocess.CalledProcessError,
    ) as error:
        parser.exit(2, f"history batch failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
