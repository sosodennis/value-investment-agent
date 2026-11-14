"""Recover real ZIP receipts for a pinned retained-parser diagnostic subset."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Never

from fundamental_service.ingestion import read_sec_xbrl_archive
from fundamental_service.original_issuer import (
    OriginalIssuerEvidenceV1,
    OriginalOperatingSourceV1,
    evaluate_original_issuer,
)
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_capture import RetainedSecSourceAdapter, SecCaptureScopeV1
from fundamental_service.sec_source import SecEdgarSourceAdapter, SecRequestPolicy
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import (
    CapturedSource,
    FilesystemContentStore,
    SnapshotError,
)

from analyze_history_study import list_value, object_value, text_value
from audit_history_study_labels import timestamp
from batch_history_study import (
    BatchIndex,
    check_original,
    fixed_targets,
    load_supplements,
)
from export_history_study_evidence import FileReference, read_evidence, runtime_pins
from plan_history_study_precision import (
    MANIFEST_DIGEST,
    ROOT,
    DesignError,
    digest,
    publish_report,
)
from read_history_originals import OriginalReader, checked_document
from read_retained_history_corpus import (
    PARSER_DIGEST,
    PROTOCOL,
    SELECTION_DIGEST,
    CorpusRow,
    check_selection,
    envelope,
    load_corpus,
    retained_report,
)


class OfflineSource(SecEdgarSourceAdapter):
    def _request(self, uri: str, *, deadline_at: datetime | None = None) -> Never:
        raise SnapshotError(
            "NETWORK_DISABLED", "no retained receipt for offline replay"
        )


@contextmanager
def file_lock(directory: Path, key: str) -> Iterator[None]:
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f"{key}.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def original_from_capture(
    row: CorpusRow, pins: dict[str, object], captured: CapturedSource
) -> OriginalIssuerEvidenceV1:
    selection, target = row.selection, row.target
    check_selection(selection, target)
    archive = object_value(selection["archive"])
    if (
        captured.uri != archive["uri"]
        or digest(captured.content) != archive["content_hash"]
        or len(captured.content) != archive["byte_length"]
        or captured.captured_at is None
        or captured.http_status != 200
        or captured.accession_number != target["accession"]
        or captured.form != "10-K"
        or captured.is_amendment
        or captured.available_at != timestamp(target["accepted_at"])
    ):
        raise SnapshotError(
            "RECOVERED_ARCHIVE_MISMATCH",
            "actual ZIP receipt differs from frozen original",
        )
    primary = text_value(selection["primary_document"])
    members = [object_value(v) for v in list_value(selection["members"])]
    content = read_sec_xbrl_archive(
        captured.content,
        primary_document=primary,
        dts_filenames=tuple(
            text_value(m["filename"]) for m in members if m["filename"] != primary
        ),
    )
    if any(
        digest(content[text_value(m["filename"])]) != m["content_hash"]
        or len(content[text_value(m["filename"])]) != m["byte_length"]
        for m in members
    ):
        raise SnapshotError(
            "RECOVERED_MEMBER_MISMATCH",
            "actual ZIP member differs from frozen parser input",
        )
    source = OriginalOperatingSourceV1(
        cik=text_value(target["cik"]),
        accession_number=text_value(target["accession"]),
        uri=captured.uri,
        content_hash=digest(captured.content),
        parser_input_hash=digest(content[primary]),
        form="10-K",
        available_at=captured.available_at,
        captured_at=captured.captured_at,
        http_status=captured.http_status,
    )
    if row.parser_output is None:
        raise DesignError("recovery requires retained parser facts")
    report = retained_report(
        row.parser_output, selection, pins, normalization_at=captured.captured_at
    )
    original = evaluate_original_issuer(
        report, source=source, decision_at=timestamp(target["valuation_timestamp"])
    )
    check_original(original, target)
    return original


def recover_row(
    row: CorpusRow,
    pins: dict[str, object],
    delegate: SecEdgarSourceAdapter,
    store: ArtifactStore,
    content: FilesystemContentStore,
    directory: Path,
) -> tuple[dict[str, object], FileReference | None, bool]:
    identity = row.identity()
    key = sha256_digest(identity)
    artifact_id = f"history-original-recovery:{key}"
    with file_lock(directory / "locks", f"attempt-{key}"):
        previous = None
        try:
            previous = checked_document(
                store.read(artifact_id), store.get(artifact_id).content_hash
            )
        except SnapshotError as error:
            if error.code != "ARTIFACT_NOT_FOUND":
                raise
        if previous is not None:
            before, outcome = envelope(previous)
            if before != identity:
                raise DesignError("retained attempt identity differs")
            if outcome["status"] == "source_refused":
                return (
                    {**outcome, "attempt_digest": sha256_digest(previous)},
                    None,
                    False,
                )
        target = row.target
        adapter = RetainedSecSourceAdapter(
            delegate,
            scope=SecCaptureScopeV1(
                cik=text_value(target["cik"]),
                accession_number=text_value(target["accession"]),
                valuation_timestamp=timestamp(target["valuation_timestamp"]),
                source_profile=PROTOCOL,
            ),
            receipts=store,
            content=content,
            capture_lock=lambda lock_key: file_lock(
                directory / "locks", f"source-{lock_key}"
            ),
        )
        original = None
        try:
            captured = adapter.capture_filing_archive(
                cik=text_value(target["cik"]),
                accession_number=text_value(target["accession"]),
                filed_at=timestamp(target["accepted_at"]),
                accepted_at=timestamp(target["accepted_at"]),
            )
            original = original_from_capture(row, pins, captured)
            outcome = {
                "status": "issuer_evidence_retained"
                if original.status == "matched"
                else "issuer_refused",
                "original_digest": sha256_digest(original),
                "issue_codes": original.issue_codes,
                "archive_hash": original.source.content_hash,
                "parser_input_hash": original.source.parser_input_hash,
            }
        except SnapshotError as error:
            if error.code == "NETWORK_DISABLED" or previous is not None:
                raise
            outcome = {
                "status": "source_refused",
                "failure_code": error.code,
                "retryable": error.retryable,
            }
        attempt = {
            "inputs": identity,
            "input_digest": key,
            "output": outcome,
            "output_digest": sha256_digest(outcome),
        }
        receipt = store.put_with_receipt(artifact_id, attempt)
        reference = None
        wrote = receipt.wrote
        if original is not None:
            publication = publish_report(
                directory / "originals", json.loads(canonical_bytes(original))
            )
            wrote |= publication["wrote"] is True
            reference = FileReference(
                path=str(
                    directory / "originals" / f"{publication['report_digest']}.json"
                ),
                sha256=sha256_digest(original),
            )
        return {**outcome, "attempt_digest": sha256_digest(attempt)}, reference, wrote


def recover_corpus(
    rows: list[CorpusRow],
    pins: dict[str, object],
    delegate: SecEdgarSourceAdapter,
    directory: Path,
) -> tuple[dict[str, object], list[FileReference], bool]:
    directory = directory.resolve()
    if any((parent / ".git").exists() for parent in (directory, *directory.parents)):
        raise DesignError("generated recovery artifacts must be outside any checkout")
    store = ArtifactStore(directory / "receipts")
    content = FilesystemContentStore(directory / "content")
    retained, originals = [], []
    wrote = False
    for row in rows:
        result: dict[str, object] = {
            **row.identity(),
            "prior_status": row.parser_row["status"],
            "prior_failure_code": row.parser_row.get("failure_code"),
            "prior_blocking_codes": row.parser_row.get("blocking_codes", []),
            "original_source_comparison": row.selection_row[
                "original_source_comparison"
            ],
            "semantic_equivalence": "not_assessed",
            "canonical_publication_approved": False,
        }
        if row.parser_row["status"] == "parsed_without_blockers":
            outcome, reference, changed = recover_row(
                row, pins, delegate, store, content, directory
            )
            result.update(outcome)
            wrote |= changed
            if reference is not None:
                originals.append(reference)
        else:
            result["status"] = "retained_ineligible"
        retained.append(result)
    return (
        {
            "rows": retained,
            "filing_count": len(rows),
            "recovery_eligible_count": sum(
                row.parser_row["status"] == "parsed_without_blockers" for row in rows
            ),
            "prior_status_counts": dict(
                sorted(
                    Counter(
                        text_value(row.parser_row["status"]) for row in rows
                    ).items()
                )
            ),
            "status_counts": dict(
                sorted(Counter(text_value(row["status"]) for row in retained).items())
            ),
            "typed_originals_retained": len(originals),
            "canonical_publication_approved": False,
            "forecasts_executed": 0,
            "supported_history_threshold": None,
        },
        originals,
        wrote,
    )


def supplement_index(
    base: BatchIndex,
    base_directory: Path,
    recovered: list[FileReference],
    targets: dict[tuple[str, str], dict[str, object]],
) -> BatchIndex:
    if base.runtime != runtime_pins() or base.fixed_manifest_digest != MANIFEST_DIGEST:
        raise DesignError("base batch index runtime or manifest differs")
    originals, _ = load_supplements(base, base_directory, targets)
    references = {
        key: FileReference(
            path=str((base_directory / ref.path).resolve()), sha256=ref.sha256
        )
        for key, (ref, _) in originals.items()
    }
    for ref in recovered:
        original = OriginalIssuerEvidenceV1.model_validate_json(
            read_evidence(ref, Path("/"))
        )
        key = f"CIK:{original.source.cik}", original.source.accession_number
        if key not in targets:
            raise DesignError("recovered original is outside the fixed cohort")
        check_original(original, targets[key])
        if key in references and references[key].sha256 != ref.sha256:
            raise DesignError("recovery cannot replace existing supplemental evidence")
        references[key] = ref
    return base.model_copy(
        update={
            "originals": tuple(ref for _, ref in sorted(references.items())),
            "seeds": tuple(
                FileReference(
                    path=str((base_directory / ref.path).resolve()), sha256=ref.sha256
                )
                for ref in base.seeds
            ),
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "manifest",
        "selection",
        "parser-report",
        "results",
        "source-repository",
        "base-index",
        "output-directory",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--exact-commit", required=True)
    parser.add_argument("--allow-network", action="store_true")
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
        pins, rows = load_corpus(
            manifest,
            args.selection.read_bytes(),
            args.parser_report.read_bytes(),
            args.results,
            OriginalReader(args.source_repository),
        )
        base_raw = args.base_index.read_bytes()
        checked_document(base_raw, digest(base_raw))
        base = BatchIndex.model_validate_json(base_raw)
        _, targets = fixed_targets(manifest)
        # Validate existing supplements before attempting provider I/O.
        supplement_index(base, args.base_index.parent, [], targets)
        if args.allow_network:
            delegate = SecEdgarSourceAdapter(
                SecRequestPolicy(
                    user_agent=os.environ.get("FUNDAMENTAL_SEC_USER_AGENT", "")
                )
            )
        else:
            delegate = OfflineSource(
                SecRequestPolicy(user_agent="offline-replay@invalid")
            )
        output, recovered, wrote = recover_corpus(
            rows, pins, delegate, args.output_directory
        )
        index = supplement_index(base, args.base_index.parent, recovered, targets)
        index_receipt = publish_report(
            args.output_directory / "indexes", json.loads(canonical_bytes(index))
        )
        inputs = {
            "issue": 376,
            "protocol": PROTOCOL,
            "exact_commit": head,
            "runtime": runtime_pins(),
            "fixed_manifest_digest": MANIFEST_DIGEST,
            "selection_digest": SELECTION_DIGEST,
            "parser_digest": PARSER_DIGEST,
            "base_index_digest": digest(base_raw),
        }
        output["batch_index_digest"] = index_receipt["report_digest"]
        report = {
            "inputs": inputs,
            "input_digest": sha256_digest(inputs),
            "output": output,
            "output_digest": sha256_digest(output),
        }
        receipt = publish_report(
            args.output_directory / "reports", json.loads(canonical_bytes(report))
        )
        print(
            json.dumps(
                {
                    **receipt,
                    "wrote": wrote or receipt["wrote"] or index_receipt["wrote"],
                    "input_digest": report["input_digest"],
                    "output_digest": report["output_digest"],
                    "batch_index_digest": index_receipt["report_digest"],
                    "status_counts": output["status_counts"],
                },
                sort_keys=True,
            )
        )
        return 0
    except (DesignError, SnapshotError, ValueError, KeyError, OSError) as error:
        print(
            json.dumps(
                {
                    "status": "refused",
                    "code": error.code
                    if isinstance(error, SnapshotError)
                    else "RECOVERY_INPUT_INVALID",
                    "message": str(error),
                },
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
