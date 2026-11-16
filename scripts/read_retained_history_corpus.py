"""Verify the complete retained parser corpus before historical source recovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fundamental_service.arelle_parser import (
    ArelleParseReportV1,
    ArelleValidationProfileV1,
    fact_semantic_digest,
)
from fundamental_service.historical_dqc import V3_PROFILE
from fundamental_service.serialization import canonical_bytes, sha256_digest

from analyze_history_study import hash_value, list_value, object_value, text_value
from audit_history_study_labels import timestamp
from batch_history_study import fixed_targets, original_from_record, target_key
from plan_history_study_precision import MANIFEST_DIGEST, DesignError
from read_history_originals import OriginalReader, checked_document

PROTOCOL = "fixed100-retained-original-receipt-recovery-v1"
SELECTION_DIGEST = "bca60230eabdaa335b2481e3cfac18bad8b72c39b982b9baf0656c34d3fcd850"
PARSER_DIGEST = "b72ee05062541e45b9122b5c49b45e327b210ccd4f93f3d950df21b725fa1857"
CORPUS_SIZE = 187
SELECTION_POLICY_DIGEST = (
    "efb9d59e7c5caa91e18ab9a764e3a5f62c3e55d317f34d082063b15b0938e36c"
)


def envelope(
    document: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    inputs, output = object_value(document["inputs"]), object_value(document["output"])
    if document["input_digest"] != sha256_digest(inputs) or document[
        "output_digest"
    ] != sha256_digest(output):
        raise DesignError("retained corpus envelope digest differs")
    return inputs, output


def retained_profile(pins: dict[str, object]) -> ArelleValidationProfileV1:
    resources = object_value(pins["resource_pins"])
    profile = ArelleValidationProfileV1(
        profile_id=V3_PROFILE.profile_id,
        dqc_version=V3_PROFILE.dqc_version,
        validation_mode="sec-efm-dqc",
        edgar_plugin_dir=Path("EDGAR"),
        xule_plugin_dir=Path("xule"),
        dqc_ruleset_path=Path("modern-dqc.zip"),
        historical_dqc_dir=Path("historical-v3"),
        edgar_plugin_sha256=hash_value(resources["EDGAR"]),
        xule_plugin_sha256=hash_value(resources["xule"]),
        dqc_ruleset_sha256=hash_value(resources["modern-dqc.zip"]),
        historical_dqc_sha256=hash_value(resources["historical-v3"]),
    )
    if profile.digest() != pins["profile_digest"]:
        raise DesignError("retained validation profile digest differs")
    return profile


def retained_report(
    output: dict[str, object],
    selection: dict[str, object],
    pins: dict[str, object],
    *,
    normalization_at: datetime,
) -> ArelleParseReportV1:
    """Reconstruct old facts; path/time normalization is not a new parser run."""
    primary = next(
        object_value(v)
        for v in list_value(selection["members"])
        if object_value(v)["filename"] == selection["primary_document"]
    )
    profile = retained_profile(pins)
    report = ArelleParseReportV1.model_validate_json(
        canonical_bytes(
            {
                "filing_path": object_value(selection["archive"])["uri"],
                "parsed_at": normalization_at,
                "parser_version": object_value(pins["runtime"])["arelle"],
                "taxonomy_version": output["taxonomy_version"],
                "validation_profile": profile.model_dump(mode="json"),
                "validation_profile_digest": profile.digest(),
                "facts": output["facts"],
                "findings": output["findings"],
                "finding_codes": sorted(
                    {object_value(v)["code"] for v in list_value(output["findings"])}
                ),
                "validation_engines": output["validation_engines"],
                "validation_evidence": output["validation_evidence"],
                "source_content_hash": primary["content_hash"],
                "taxonomy_cache_hash": pins["taxonomy_cache_pin"],
                "offline": True,
                "network_attempt_count": output["network_attempt_count"],
            }
        )
    )
    if (
        report.replay_digest() != output["report_replay_digest"]
        or fact_semantic_digest(report) != output["fact_semantic_digest"]
        or len(report.facts) != output["fact_count"]
        or report.network_attempt_count != 0
        or list(report.blocking_finding_codes()) != output["blocking_codes"]
        or (not report.blocking_finding_codes())
        != (output["status"] == "parsed_without_blockers")
    ):
        raise DesignError("retained parser facts, replay or blocker evidence differs")
    return report


@dataclass(frozen=True)
class CorpusRow:
    selection_row: dict[str, object]
    parser_row: dict[str, object]
    parser_output: dict[str, object] | None

    @property
    def target(self) -> dict[str, object]:
        return object_value(self.selection_row["target"])

    @property
    def selection(self) -> dict[str, object]:
        return object_value(self.selection_row["selection"])

    def identity(self) -> dict[str, object]:
        return {
            "protocol": PROTOCOL,
            "fixed_manifest_digest": MANIFEST_DIGEST,
            "selection_corpus_digest": SELECTION_DIGEST,
            "parser_corpus_digest": PARSER_DIGEST,
            "target": self.target,
            "selection_digest": self.selection_row.get("selection_digest"),
            "retained_result_digest": self.parser_row.get("report_digest"),
            "original_result_digest": self.selection_row["original_result_digest"],
        }


def check_selection(selection: dict[str, object], target: dict[str, object]) -> None:
    root = (
        f"https://www.sec.gov/Archives/edgar/data/{int(text_value(target['cik']))}/"
        f"{text_value(target['accession']).replace('-', '')}/"
    )
    members = [object_value(v) for v in list_value(selection["members"])]
    names = [text_value(v["filename"]) for v in members]
    if (
        any(
            selection[k] != target[k]
            for k in ("cik", "accession", "accepted_at", "valuation_timestamp")
        )
        or target["form"] != "10-K"
        or selection["policy_digest"] != SELECTION_POLICY_DIGEST
        or selection["policy_id"] != "sec-original-xbrl-archive-v1"
        or selection["semantic_equivalence"] != "not_assessed"
        or selection["canonical_publication_approved"] is not False
        or len(set(names)) != len(names)
        or selection["primary_document"] not in names
        or any(
            not name or "/" in name or "\\" in name or name in (".", "..")
            for name in names
        )
        or object_value(selection["archive"])["uri"]
        != f"{root}{target['accession']}-xbrl.zip"
    ):
        raise DesignError("frozen original archive selection differs")
    for role, filename in (
        ("archive", f"{target['accession']}-xbrl.zip"),
        ("index", "index.json"),
        ("direct", selection["primary_document"]),
    ):
        source = object_value(selection[role])
        if (
            source["uri"] != f"{root}{filename}"
            or source["available_at"] != target["accepted_at"]
        ):
            raise DesignError("frozen source URI or availability differs")


def load_corpus(
    manifest: dict[str, object],
    selection_raw: bytes,
    parser_raw: bytes,
    results: Path,
    reader: OriginalReader,
) -> tuple[dict[str, object], list[CorpusRow]]:
    """Verify the entire pinned corpus before any provider I/O or publication."""
    _, targets = fixed_targets(manifest)
    _, selections = envelope(checked_document(selection_raw, SELECTION_DIGEST))
    pins, parsed = envelope(checked_document(parser_raw, PARSER_DIGEST))
    if pins["selection_report_digest"] != SELECTION_DIGEST:
        raise DesignError("parser corpus selection pin differs")
    retained_profile(pins)
    original_refs = {
        text_value(object_value(v)["sha256"]): v
        for v in list_value(manifest["original_filing_outcome_refs"])
    }
    selection_rows = {
        target_key(object_value(row["target"])): row
        for v in list_value(selections["rows"])
        for row in (object_value(v),)
    }
    parser_rows = {
        target_key(object_value(row["target"])): row
        for v in list_value(parsed["rows"])
        for row in (object_value(v),)
    }
    if (
        len(selection_rows) != CORPUS_SIZE
        or len(list_value(selections["rows"])) != CORPUS_SIZE
        or len(list_value(parsed["rows"])) != CORPUS_SIZE
        or set(selection_rows) != set(parser_rows)
    ):
        raise DesignError("complete unique retained corpus is required")
    rows = []
    for key, selected in sorted(selection_rows.items()):
        row = parser_rows[key]
        target = object_value(selected["target"])
        original_digest = text_value(selected["original_result_digest"])
        if (
            key not in targets
            or target != targets[key]
            or row["target"] != target
            or original_digest not in original_refs
            or selected["publication_approved"] is not False
            or row[
                "canonical_publication_approved"
                if "report_digest" in row
                else "publication_approved"
            ]
            is not False
        ):
            raise DesignError(
                "retained corpus contains a substituted target or authority"
            )
        original = reader.document(original_refs[original_digest])
        if (
            original_from_record(original, target) is not None
            or object_value(original["output"])["code"]
            != "SOURCE_ARCHIVE_SIZE_MISMATCH"
        ):
            raise DesignError("retained corpus must preserve original size refusals")
        output = None
        if selected["selection_status"] == "refused":
            if (
                row["status"] != "selection_refused"
                or row["original_result_digest"] != original_digest
                or row["failure_code"] != selected["failure_code"]
            ):
                raise DesignError("retained selection refusal differs")
        else:
            selection = object_value(selected["selection"])
            check_selection(selection, target)
            if sha256_digest(selection) != selected["selection_digest"]:
                raise DesignError("retained selection digest differs")
            result_digest = hash_value(row["report_digest"])
            result_path = results / f"{result_digest}.json"
            if (
                result_path.is_symlink()
                or result_path.resolve().parent != results.resolve()
            ):
                raise DesignError("retained result escapes its directory")
            record = checked_document(result_path.read_bytes(), result_digest)
            inputs, output = envelope(record)
            if (
                inputs
                != {
                    "protocol_input_digest": sha256_digest(pins),
                    "selection_digest": selected["selection_digest"],
                    "target": target,
                }
                or row["input_digest"] != record["input_digest"]
                or row["output_digest"] != record["output_digest"]
                or row["status"] != output["status"]
                or output["canonical_publication_approved"] is not False
            ):
                raise DesignError("retained parser result or input differs")
            if output["status"] in ("parsed_without_blockers", "parsed_with_blockers"):
                # Only a transient normalization: replay_digest excludes time.
                # Exported reports use the real ZIP receipt's capture time.
                retained_report(
                    output,
                    selection,
                    pins,
                    normalization_at=timestamp(target["accepted_at"]),
                )
            elif (
                output["status"] != "parser_refused"
                or row["failure_code"] != output["failure_code"]
            ):
                raise DesignError("unknown retained parser result")
        rows.append(CorpusRow(selected, row, output))
    return pins, rows
