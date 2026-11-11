"""Validate every frozen historical filing without publishing canonical data."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Literal, TypedDict

from pydantic import AwareDatetime, Field, model_validator

from .arelle_parser import ArelleParserError, ArelleValidationProfileV1
from .contracts import IdentityV1, StrictModel
from .history_mapping_audit import (
    _decision_targets,
    _filings,
    _load_snapshot_for,
    _read_json,
    _selected_issuers,
)
from .ingestion import SecIngestionService
from .operations import ServiceError
from .sec_capture import SecCaptureScopeV1, SecCaptureStore
from .sec_source import SecEdgarSourceAdapter
from .serialization import canonical_bytes, sha256_digest
from .snapshots import CapturedSource, SnapshotError
from .source_acquisition import SecAcquisitionUseCase

COHORT_SHA256 = "afad3f92f2597383d16afec2cc85850fbf5919106d3cb827a6e8112022836242"
SOURCE_PROFILE = "sec-fixed100-original-validation-v1"


class _FilingArguments(TypedDict):
    cik: str
    accession_number: str
    filed_at: datetime
    accepted_at: datetime
    form: str
    is_amendment: bool
    deadline_at: datetime


class OriginalValidationTargetV1(StrictModel):
    issuer_id: str
    cik: str = Field(pattern=r"^\d{10}$")
    accession: str = Field(pattern=r"^\d{10}-\d{2}-\d{6}$")
    form: Literal["10-K", "10-K/A"]
    period_end: date
    accepted_at: AwareDatetime
    valuation_timestamp: AwareDatetime
    role: Literal["history", "decision", "label"]

    @model_validator(mode="after")
    def available_at_cutoff(self) -> OriginalValidationTargetV1:
        if self.issuer_id != f"CIK:{self.cik}":
            raise ValueError("target CIK and issuer differ")
        if self.accepted_at > self.valuation_timestamp:
            raise ValueError("original filing is not available at the fixed cutoff")
        if self.role != "history" and self.form != "10-K":
            raise ValueError("decision and label require original annual filings")
        return self


class OriginalIssuer(TypedDict):
    issuer_id: str
    decision_accession: str
    decision_at: datetime
    label_accession: str | None
    label_missing_reason: str | None
    snapshot_sha256: object


class OriginalInventory(TypedDict):
    protocol_version: str
    cohort_digest: str
    issuers: list[OriginalIssuer]
    targets: list[OriginalValidationTargetV1]


class RetainedOriginalResult(TypedDict):
    input_digest: str
    inputs: dict[str, object]
    output_digest: str
    output: dict[str, object]


def original_inventory(root: Path, manifest: Path) -> OriginalInventory:
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != COHORT_SHA256:
        raise ValueError("original validation cannot replace the fixed cohort")
    targets: list[OriginalValidationTargetV1] = []
    issuers: list[OriginalIssuer] = []
    for row in _selected_issuers(_read_json(manifest, "fixed cohort"), root=root):
        issuer = str(row["issuer_id"])
        filings = _filings(_load_snapshot_for(root, row), issuer)
        decision, _, label, allowed = _decision_targets(
            filings, str(row["decision_accession"])
        )
        issuers.append(
            {
                "issuer_id": issuer,
                "decision_accession": decision.accession,
                "decision_at": decision.accepted_at,
                "label_accession": label.accession if label else None,
                "label_missing_reason": None
                if label
                else "no_first_subsequent_original",
                "snapshot_sha256": row["snapshot_sha256"],
            }
        )
        for filing in filings:
            if filing.accession not in allowed:
                continue
            is_label = label is not None and filing.accession == label.accession
            targets.append(
                OriginalValidationTargetV1(
                    issuer_id=issuer,
                    cik=str(row["cik"]),
                    accession=filing.accession,
                    form="10-K/A" if filing.form == "10-K/A" else "10-K",
                    period_end=filing.period_end,
                    accepted_at=filing.accepted_at,
                    valuation_timestamp=filing.accepted_at
                    if is_label
                    else decision.accepted_at,
                    role="label"
                    if is_label
                    else "decision"
                    if filing == decision
                    else "history",
                )
            )
    targets.sort(
        key=lambda t: (t.valuation_timestamp, t.issuer_id, t.accepted_at, t.accession)
    )
    if len(issuers) != 100 or len({i["issuer_id"] for i in issuers}) != 100:
        raise ValueError("fixed original inventory must retain all100 issuers")
    return {
        "protocol_version": SOURCE_PROFILE,
        "cohort_digest": COHORT_SHA256,
        "issuers": sorted(issuers, key=lambda i: str(i["issuer_id"])),
        "targets": targets,
    }


def _source_evidence(source: CapturedSource) -> dict[str, object]:
    return {
        "uri": source.uri,
        "content_hash": hashlib.sha256(source.content).hexdigest(),
        "available_at": source.available_at,
        "accession": source.accession_number,
        "form": source.form,
        "media_type": source.media_type,
    }


def validate_original(
    target: OriginalValidationTargetV1,
    *,
    service: SecIngestionService,
    adapter: SecEdgarSourceAdapter,
    profile: ArelleValidationProfileV1,
    cache: Path,
    deadline_at: datetime,
) -> dict[str, object]:
    """Use the owning ingestion prepare path; its snapshot is never published."""
    sources = []
    try:
        index = adapter.capture_filing_index(
            cik=target.cik,
            accession_number=target.accession,
            filed_at=target.accepted_at,
            deadline_at=deadline_at,
        )
        sources.append(_source_evidence(index))
        selector = object.__new__(SecAcquisitionUseCase)
        # This diagnostic policy requires one original schema-bound standalone
        # instance. Ambiguous/inline-only packages fail rather than guessing.
        entry = selector._select_xbrl_entrypoint(
            index.content, "", is_inline_xbrl=False
        )
        dts = selector._select_dts_filenames(index.content, entry)
        archive_name = selector._select_filing_archive_filename(
            index.content, target.accession
        )
        common: _FilingArguments = dict(
            cik=target.cik,
            accession_number=target.accession,
            filed_at=target.accepted_at,
            accepted_at=target.accepted_at,
            form=target.form,
            is_amendment=target.form == "10-K/A",
            deadline_at=deadline_at,
        )
        original = adapter.capture_filing(primary_document=entry, **common)
        sources.append(_source_evidence(original))
        archive = adapter.capture_filing_archive(filename=archive_name, **common)
        sources.append(_source_evidence(archive))
        captured_at = max(
            s.captured_at or s.available_at for s in (index, original, archive)
        )
        prepared = service.prepare_filing(
            identity=IdentityV1(
                issuer_id=target.issuer_id,
                issuer_name="Original-source diagnostic only",
                domicile="US",
                reporting_basis="us-gaap",
                security_id=f"diagnostic:{target.issuer_id}",
                share_class="unresolved-diagnostic",
                currency="USD",
            ),
            primary_document=entry,
            filing_archive_filename=archive_name,
            captured_at=captured_at,
            valuation_timestamp=target.valuation_timestamp,
            parser_version=profile.arelle_version,
            policy_version="pit-v1",
            taxonomy_manifest_id="sec-original-diagnostic-only",
            taxonomy_version="original-filing-namespaces",
            taxonomy_cache_dir=cache,
            mappings=(),
            reference_sources=(index,),
            dts_filenames=dts,
            profile=profile,
            source_adapter=adapter,
            **common,
        )
        report = prepared.parser_report
        parsed = report.model_dump(mode="json", exclude={"filing_path", "parsed_at"})
        parsed["facts"] = sorted(parsed["facts"], key=sha256_digest)
        parsed["findings"] = sorted(parsed["findings"], key=sha256_digest)
        return {
            "status": "validation_passed_unpublished",
            "sources": sources,
            "parser_digest": report.replay_digest(),
            "parser_report": parsed,
            "integrity_evidence": prepared.integrity_evidence,
            "canonical_snapshot_published": False,
            "canonical_release_published": False,
        }
    except ArelleParserError as error:
        failure = error.validation_failure
        return {
            "status": "refused",
            "code": error.code,
            "sources": sources,
            "validation_failure": failure,
            "canonical_snapshot_published": False,
            "canonical_release_published": False,
        }
    except (SnapshotError, ServiceError) as error:
        return {
            "status": "refused",
            "code": error.code,
            "sources": sources,
            "retryable": error.retryable,
            "evidence_ref": getattr(error, "evidence_ref", None),
            "canonical_snapshot_published": False,
            "canonical_release_published": False,
        }


def retained_original_result(
    inputs: dict[str, object],
    *,
    artifacts: SecCaptureStore,
    evaluate: Callable[[], dict[str, object]],
) -> tuple[RetainedOriginalResult, bool]:
    """Freeze successful and failed observations; repeats never re-fetch originals."""
    input_digest = sha256_digest(inputs)
    artifact_id = f"history-original-validation:{input_digest}"
    try:
        record = artifacts.get(artifact_id)
    except SnapshotError as error:
        if error.code != "ARTIFACT_NOT_FOUND":
            raise
    else:
        if record.retention != "evidence" or record.status != "valid":
            raise ValueError("retained original validation is not valid evidence")
        result: RetainedOriginalResult = json.loads(artifacts.read(artifact_id))
        if (
            result.get("input_digest") != input_digest
            or result.get("inputs") != json.loads(canonical_bytes(inputs))
            or result.get("output_digest") != sha256_digest(result.get("output"))
        ):
            raise ValueError("retained original validation digest/input mismatch")
        return result, False
    output = evaluate()
    result = {
        "input_digest": input_digest,
        "inputs": inputs,
        "output_digest": sha256_digest(output),
        "output": output,
    }
    artifacts.put(artifact_id, result, retention="evidence")
    return result, True


def capture_scope(target: OriginalValidationTargetV1) -> SecCaptureScopeV1:
    return SecCaptureScopeV1(
        cik=target.cik,
        accession_number=target.accession,
        valuation_timestamp=target.valuation_timestamp,
        source_profile=SOURCE_PROFILE,
    )
