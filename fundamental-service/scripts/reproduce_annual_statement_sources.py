"""Capture or verify the fixed annual originals without granting data authority."""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable, Sequence
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Literal

from filelock import FileLock
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from fundamental_service.annual_discovery import (
    AnnualDiscoveryRequestV1,
    AnnualFilingV1,
)
from fundamental_service.annual_discovery_service import AnnualDiscovery
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_capture import (
    RetainedSecSourceAdapter,
    SecCaptureScopeV1,
    SecResponseReceiptV1,
    SecStoredResponseV1,
    sec_response_artifact_id,
)
from fundamental_service.sec_source import (
    SecEdgarSourceAdapter,
    SecRequestPolicy,
    SecRequestTransportPort,
    _SecResponse,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import (
    CapturedSource,
    FilesystemContentStore,
    SnapshotError,
)

DEFAULT_COHORT = (
    Path(__file__).resolve().parents[1]
    / "tests/fixtures/annual-statements/issue494-cohort.json"
)


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CaptureRevision(FrozenModel):
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")


class ReceiptReference(FrozenModel):
    artifact_id: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    retained_path: str
    schema_version: Literal["sec-response-receipt.v1"]
    scope: SecCaptureScopeV1


class FrozenSource(SecStoredResponseV1):
    receipt_refs: tuple[ReceiptReference, ...] = Field(min_length=1)

    def observation(self) -> SecStoredResponseV1:
        return SecStoredResponseV1.model_validate(
            self.model_dump(exclude={"receipt_refs"})
        )


class FrozenFiling(AnnualFilingV1):
    model_config = ConfigDict(extra="ignore", frozen=True)
    issuer_id: str = Field(pattern=r"^[0-9]{10}$")
    source_records: tuple[FrozenSource, ...] = Field(min_length=4, max_length=4)

    def selection(self) -> AnnualFilingV1:
        return AnnualFilingV1.model_validate(
            self.model_dump(include=set(AnnualFilingV1.model_fields))
        )

    @model_validator(mode="after")
    def sources_belong_to_original(self) -> FrozenFiling:
        prefix = (
            f"https://www.sec.gov/Archives/edgar/data/{int(self.issuer_id)}/"
            f"{self.accession_number.replace('-', '')}/"
        )
        expected = {
            prefix + "index.json",
            prefix + f"{self.accession_number}-xbrl.zip",
            prefix + self.primary_document,
            prefix + f"{self.accession_number}.txt",
        }
        if {source.uri for source in self.source_records} != expected:
            raise ValueError("frozen source URLs must belong to the exact original")
        for source in self.source_records:
            for reference in source.receipt_refs:
                scope = reference.scope
                if (
                    scope.cik != self.issuer_id
                    or scope.accession_number != self.accession_number
                    or reference.artifact_id
                    != sec_response_artifact_id(scope, source.uri)
                ):
                    raise ValueError("frozen receipt scope differs from its original")
        return self


class FrozenCase(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    case_id: str
    issuer_id: str = Field(pattern=r"^[0-9]{10}$")
    cutoff_at: AwareDatetime
    original_accessions: tuple[str, ...] = Field(min_length=1, max_length=6)
    discovery_artifact_id: str
    discovery_evidence_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class FrozenCohort(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    protocol: Literal["issue494-annual-statements-cohort-v1"]
    source_baseline: str = Field(pattern=r"^[0-9a-f]{40}$")
    cases: tuple[FrozenCase, ...] = Field(min_length=1)
    filings: tuple[FrozenFiling, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def cases_retain_every_original(self) -> FrozenCohort:
        filings = {filing.accession_number: filing for filing in self.filings}
        if len(filings) != len(self.filings) or len(
            {case.case_id for case in self.cases}
        ) != len(self.cases):
            raise ValueError("frozen cases and originals must be unique")
        for case in self.cases:
            if len(set(case.original_accessions)) != len(case.original_accessions):
                raise ValueError("frozen original selection contains duplicates")
            for accession in case.original_accessions:
                filing = filings.get(accession)
                if (
                    filing is None
                    or filing.issuer_id != case.issuer_id
                    or filing.accepted_at > case.cutoff_at
                ):
                    raise ValueError(
                        "frozen original differs from its issuer or cutoff"
                    )
                for source in filing.source_records:
                    if not any(
                        ref.scope.valuation_timestamp == case.cutoff_at
                        for ref in source.receipt_refs
                    ):
                        raise ValueError("frozen original lacks its cutoff receipt")
        return self


class SourceCheck(FrozenModel):
    issuer_id: str
    accession_number: str
    source_url: str
    expected_content_hash: str
    receipt_artifact_id: str
    receipt_content_hash: str | None = None
    actual: SecResponseReceiptV1 | None = None
    changed_fields: tuple[str, ...] = ()
    issue_codes: tuple[str, ...] = ()


class CaseCheck(FrozenModel):
    case_id: str
    expected_accessions: tuple[str, ...]
    selected_accessions: tuple[str, ...] = ()
    discovery_artifact_id: str | None = None
    discovery_digest: str | None = None
    changed_fields: tuple[str, ...] = ()
    issue_codes: tuple[str, ...] = ()


class ReproductionReport(FrozenModel):
    protocol: Literal["issue494-annual-source-reproduction-v1"] = (
        "issue494-annual-source-reproduction-v1"
    )
    mode: Literal["verify_frozen", "capture_new_inputs"]
    cohort_sha256: str
    declared_source_revision: str
    cases: tuple[CaseCheck, ...]
    sources: tuple[SourceCheck, ...]
    validation_performed: Literal[False] = False
    canonical_ingestion_performed: Literal[False] = False

    @property
    def exit_code(self) -> int:
        return (
            2
            if any(item.issue_codes or item.changed_fields for item in self.cases)
            or any(item.issue_codes for item in self.sources)
            else 0
        )


class OfflineTransport:
    policy = SecRequestPolicy(user_agent="frozen-input-check offline@invalid.local")

    def _request(
        self, uri: str, *, deadline_at: datetime | None = None
    ) -> _SecResponse:
        raise AssertionError("offline verification attempted provider I/O")


def _compare_source(
    filing: FrozenFiling,
    expected: FrozenSource,
    reference: ReceiptReference,
    artifacts: ArtifactStore,
    content: FilesystemContentStore,
    *,
    frozen: bool = False,
) -> SourceCheck:
    try:
        record = artifacts.get(reference.artifact_id)
        raw = artifacts.read(reference.artifact_id)
        if frozen:
            retained_path = (artifacts.root.parent / reference.retained_path).resolve()
            if (
                artifacts.root.resolve() not in retained_path.parents
                or retained_path.read_bytes() != raw
            ):
                raise SnapshotError(
                    "SOURCE_RECEIPT_PATH_INVALID", "retained receipt path differs"
                )
        actual = SecResponseReceiptV1.model_validate_json(raw)
        payload = content.get(actual.content_hash, media_type=actual.media_type)
        if (
            record.status != "valid"
            or record.retention != "evidence"
            or record.media_type != "application/json"
            or record.dependency_hashes != (actual.content_hash,)
            or raw != canonical_bytes(actual)
            or actual.scope != reference.scope
            or actual.uri != expected.uri
            or sha256(payload).hexdigest() != actual.content_hash
            or len(payload) != actual.received_size
        ):
            raise SnapshotError("SOURCE_RECEIPT_INVALID", "source evidence differs")
        expected_observation = expected.observation()
        changed = tuple(
            name
            for name in SecStoredResponseV1.model_fields
            if getattr(actual, name) != getattr(expected_observation, name)
        )
        codes = []
        if actual.content_hash != expected.content_hash:
            codes.append("SOURCE_CONTENT_DIFFERENT")
        if any(field != "content_hash" for field in changed):
            codes.append("SOURCE_CAPTURE_METADATA_DIFFERENT")
        if record.content_hash != reference.content_hash:
            codes.append("SOURCE_RECEIPT_DIFFERENT")
        return SourceCheck(
            issuer_id=filing.issuer_id,
            accession_number=filing.accession_number,
            source_url=expected.uri,
            expected_content_hash=expected.content_hash,
            receipt_artifact_id=reference.artifact_id,
            receipt_content_hash=record.content_hash,
            actual=actual,
            changed_fields=changed,
            issue_codes=tuple(codes),
        )
    except (SnapshotError, OSError, ValueError) as error:
        return SourceCheck(
            issuer_id=filing.issuer_id,
            accession_number=filing.accession_number,
            source_url=expected.uri,
            expected_content_hash=expected.content_hash,
            receipt_artifact_id=reference.artifact_id,
            issue_codes=(
                error.code
                if isinstance(error, SnapshotError)
                else "SOURCE_EVIDENCE_INVALID",
            ),
        )


def _selected_filings(
    cohort: FrozenCohort, case: FrozenCase
) -> tuple[FrozenFiling, ...]:
    by_accession = {filing.accession_number: filing for filing in cohort.filings}
    return tuple(by_accession[accession] for accession in case.original_accessions)


def verify_frozen(
    cohort: FrozenCohort, *, cohort_hash: str, evidence_dir: Path
) -> ReproductionReport:
    if (
        not (evidence_dir / "content").is_dir()
        or not (evidence_dir / "artifacts/.artifact-records.jsonl").is_file()
        or not (evidence_dir / "artifacts/.artifact-records.lock").is_file()
    ):
        raise ValueError(
            "frozen evidence requires existing content and artifact inventory"
        )
    artifacts = ArtifactStore(evidence_dir / "artifacts")
    content = FilesystemContentStore(evidence_dir / "content")
    discovery = AnnualDiscovery(
        provider=OfflineTransport(),
        artifacts=artifacts,
        content=content,
        capture_lock=lambda key: nullcontext(),
    )
    checks = []
    for case in cohort.cases:
        codes: tuple[str, ...] = ()
        selected: tuple[str, ...] = ()
        digest = None
        try:
            evidence = discovery.read(case.discovery_artifact_id)
            digest = evidence.digest
            selected = tuple(f.accession_number for f in evidence.selection.selected)
            if (
                digest != case.discovery_evidence_digest
                or evidence.request.cik != case.issuer_id
                or evidence.request.valuation_timestamp != case.cutoff_at
                or selected != case.original_accessions
                or evidence.selection.issue_codes
            ):
                codes = ("FROZEN_DISCOVERY_MISMATCH",)
        except (SnapshotError, OSError, ValueError) as error:
            codes = (
                error.code
                if isinstance(error, SnapshotError)
                else "FROZEN_DISCOVERY_INVALID",
            )
        checks.append(
            CaseCheck(
                case_id=case.case_id,
                expected_accessions=case.original_accessions,
                selected_accessions=selected,
                discovery_artifact_id=case.discovery_artifact_id,
                discovery_digest=digest,
                issue_codes=codes,
            )
        )
    return ReproductionReport(
        mode="verify_frozen",
        cohort_sha256=cohort_hash,
        declared_source_revision=cohort.source_baseline,
        cases=tuple(checks),
        sources=tuple(
            _compare_source(filing, source, ref, artifacts, content, frozen=True)
            for filing in cohort.filings
            for source in filing.source_records
            for ref in source.receipt_refs
        ),
    )


def capture_sources(
    cohort: FrozenCohort,
    *,
    cohort_hash: str,
    evidence_dir: Path,
    provider: SecRequestTransportPort,
    source_revision: str,
    deadline_at: datetime,
) -> ReproductionReport:
    previous = (evidence_dir / "artifacts/.artifact-records.jsonl").is_file()
    artifacts = ArtifactStore(evidence_dir / "artifacts")
    capture_input = {
        "protocol": "issue494-annual-source-capture-input-v1",
        "cohort_sha256": cohort_hash,
        "source_revision": source_revision,
    }
    input_id = "annual-source-capture-input:" + sha256_digest(capture_input)
    if previous:
        try:
            if artifacts.read(input_id) != canonical_bytes(capture_input):
                raise ValueError("capture request identity differs")
        except SnapshotError as error:
            raise ValueError(
                "capture requires a new evidence directory or the same capture request"
            ) from error
    artifacts.put_with_receipt(input_id, capture_input)
    content = FilesystemContentStore(evidence_dir / "content")
    locks = evidence_dir / "locks"
    locks.mkdir(parents=True, exist_ok=True)

    def capture_lock(key: str) -> FileLock:
        return FileLock(locks / f"{key}.lock", timeout=30)

    discovery = AnnualDiscovery(
        provider=provider,
        artifacts=artifacts,
        content=content,
        capture_lock=capture_lock,
    )
    checks: list[CaseCheck] = []
    sources: list[SourceCheck] = []
    for case in cohort.cases:
        originals = _selected_filings(cohort, case)
        request = AnnualDiscoveryRequestV1(
            cik=case.issuer_id,
            valuation_timestamp=case.cutoff_at,
            declared_source_revision=source_revision,
            original_count=len(originals),
            supported_filing_years=tuple(
                sorted({f.filing_date.year for f in cohort.filings})
            ),
        )
        evidence, _ = discovery.execute(request, deadline_at=deadline_at)
        selected = tuple(f.accession_number for f in evidence.selection.selected)
        codes = evidence.selection.issue_codes
        if evidence.selection.selected != tuple(f.selection() for f in originals):
            codes = tuple(sorted({*codes, "FROZEN_SELECTION_DIFFERENT"}))
        changed = (
            ("discovery_evidence_digest",)
            if evidence.digest != case.discovery_evidence_digest
            else ()
        )
        checks.append(
            CaseCheck(
                case_id=case.case_id,
                expected_accessions=case.original_accessions,
                selected_accessions=selected,
                discovery_artifact_id=evidence.artifact_id,
                discovery_digest=evidence.digest,
                changed_fields=changed,
                issue_codes=codes,
            )
        )
        if codes:
            continue
        for filing in originals:
            references = {
                source.uri: next(
                    ref
                    for ref in source.receipt_refs
                    if ref.scope.valuation_timestamp == case.cutoff_at
                )
                for source in filing.source_records
            }
            scope = next(iter(references.values())).scope
            adapter = RetainedSecSourceAdapter(
                provider,
                scope=scope,
                receipts=artifacts,
                content=content,
                capture_lock=capture_lock,
            )
            kwargs = {
                "cik": filing.issuer_id,
                "accession_number": filing.accession_number,
                "filed_at": filing.accepted_at,
                "deadline_at": deadline_at,
            }
            actions: dict[str, Callable[[], CapturedSource]] = {
                "index.json": lambda: adapter.capture_filing_index(**kwargs),
                f"{filing.accession_number}-xbrl.zip": lambda: adapter.capture_filing_archive(
                    **kwargs
                ),
                filing.primary_document: lambda: adapter.capture_filing(
                    primary_document=filing.primary_document, **kwargs
                ),
                f"{filing.accession_number}.txt": lambda: adapter.capture_filing_submission(
                    **kwargs
                ),
            }
            for source in filing.source_records:
                try:
                    actions[source.uri.rsplit("/", 1)[1]]()
                    check = _compare_source(
                        filing, source, references[source.uri], artifacts, content
                    )
                except SnapshotError as error:
                    check = SourceCheck(
                        issuer_id=filing.issuer_id,
                        accession_number=filing.accession_number,
                        source_url=source.uri,
                        expected_content_hash=source.content_hash,
                        receipt_artifact_id=references[source.uri].artifact_id,
                        issue_codes=(error.code,),
                    )
                sources.append(check)
    report = ReproductionReport(
        mode="capture_new_inputs",
        cohort_sha256=cohort_hash,
        declared_source_revision=source_revision,
        cases=tuple(checks),
        sources=tuple(sources),
    )
    artifacts.put_with_receipt(
        "annual-source-reproduction:" + sha256_digest(report),
        report,
        dependency_hashes=tuple(
            sorted(
                {
                    item.receipt_content_hash
                    for item in report.sources
                    if item.receipt_content_hash is not None
                }
            )
        ),
    )
    return report


def _write_report(report: ReproductionReport, output: Path) -> None:
    payload = canonical_bytes(report)
    if output.exists():
        if output.read_bytes() != payload:
            raise ValueError("report already exists with different content")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as handle:
        handle.write(payload)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("verify", "capture"))
    parser.add_argument("--cohort", type=Path, default=DEFAULT_COHORT)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-revision")
    parser.add_argument("--user-agent-env", default="FUNDAMENTAL_SEC_USER_AGENT")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args(argv)
    try:
        if (
            args.output.resolve() == args.evidence_dir.resolve()
            or args.evidence_dir.resolve() in args.output.resolve().parents
        ):
            raise ValueError("report output must be outside retained evidence")
        payload = args.cohort.read_bytes()
        cohort = FrozenCohort.model_validate_json(payload)
        cohort_hash = sha256(payload).hexdigest()
        if args.mode == "verify":
            report = verify_frozen(
                cohort, cohort_hash=cohort_hash, evidence_dir=args.evidence_dir
            )
        else:
            source_revision = CaptureRevision(
                source_revision=args.source_revision
            ).source_revision
            if not 1 <= args.timeout_seconds <= 3600:
                raise ValueError("timeout must be between 1 and 3600 seconds")
            provider = SecEdgarSourceAdapter(
                SecRequestPolicy(
                    user_agent=os.environ.get(args.user_agent_env, ""),
                    min_interval_seconds=0.25,
                )
            )
            report = capture_sources(
                cohort,
                cohort_hash=cohort_hash,
                evidence_dir=args.evidence_dir,
                provider=provider,
                source_revision=source_revision,
                deadline_at=datetime.now(UTC) + timedelta(seconds=args.timeout_seconds),
            )
        _write_report(report, args.output)
    except (OSError, ValueError, SnapshotError) as error:
        parser.exit(2, f"source reproduction failed: {error}\n")
    print(
        canonical_bytes(
            {
                "mode": report.mode,
                "report_sha256": sha256_digest(report),
                "cases": len(report.cases),
                "source_receipts": len(report.sources),
                "frozen_inputs_match": report.exit_code == 0,
                "validation_performed": False,
                "exit_code": report.exit_code,
            }
        ).decode()
    )
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
