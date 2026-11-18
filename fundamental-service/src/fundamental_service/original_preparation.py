"""Persistent original validation and security selection before source plans."""

from __future__ import annotations

import hashlib
import sys
import tempfile
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, TypeVar

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from .annual_discovery import AnnualFilingV1
from .annual_discovery_service import AnnualDiscovery, AnnualDiscoveryEvidenceV1
from .arelle_parser import ParsedXbrlFactV1, fact_semantic_digest
from .command_artifacts import EvidenceArtifactStore
from .contracts import (
    IdentityV1,
    SecCapturedSourceEvidenceV1,
    SecIntegrityEvidenceV1,
    StrictModel,
)
from .data_releases import ArtifactRefV1
from .issuer_identity import (
    IdentityResolutionError,
    OriginalHistoryIdentityPolicy,
    OriginalSecuritySelectionPolicy,
    original_history_identity_key,
    original_identity_evidence_facts,
    resolve_original_filing_identity,
)
from .original_issuer import OriginalIssuerEvidenceChecks, OriginalIssuerEvidenceV1
from .parser_action_evidence import require_parser_action_evidence
from .parser_action_contracts import parser_action_markers
from .parser_action_identity import ParserBuildChecks
from .regulatory_validation import require_sec_validation_evidence
from .replay import ArtifactPublicationV1, ArtifactRecordV1
from .sec_capture import (
    SecCaptureScopeV1,
    SecResponseReceiptV1,
    sec_response_artifact_id,
)
from .parser_computation import execution_validation_evidence
from .serialization import canonical_bytes, sha256_digest
from .snapshots import ContentAddressedStore, SnapshotError


class OriginalValidationRuntimeV1(StrictModel):
    declared_source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    taxonomy_manifest_id: str = Field(min_length=1)
    taxonomy_version: str = Field(min_length=1)
    taxonomy_cache_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_profile_id: Literal[
        "sec-efm-us-dqc-v31.0.3", "sec-efm-us-dqc-v1.0.0-historical"
    ] = "sec-efm-us-dqc-v31.0.3"
    supported_filing_years: tuple[int, ...]
    supported_filing_forms: tuple[str, ...]
    source_max_response_bytes: int = Field(gt=0)
    source_max_submission_bytes: int = Field(gt=0)
    python_version: str = Field(min_length=1)
    pydantic_version: str = Field(min_length=1)
    arelle_version: Literal["2.47.4"] = "2.47.4"


class OriginalValidationRequestV1(StrictModel):
    protocol: Literal["sec-original-validation-v1"] = "sec-original-validation-v1"
    cik: str = Field(pattern=r"^[0-9]{10}$")
    valuation_timestamp: AwareDatetime
    filing: AnnualFilingV1
    runtime: OriginalValidationRuntimeV1
    source_selection_policy: Literal["sec-pit-v1"] = "sec-pit-v1"

    @property
    def scope(self) -> SecCaptureScopeV1:
        return SecCaptureScopeV1(
            cik=self.cik,
            accession_number=self.filing.accession_number,
            valuation_timestamp=self.valuation_timestamp,
            source_profile=self.source_selection_policy,
        )

    @property
    def digest(self) -> str:
        return sha256_digest(self)


class OriginalValidationEvidenceV1(StrictModel):
    request: OriginalValidationRequestV1
    responses: tuple[SecResponseReceiptV1, ...] = ()
    captured_sources: tuple[SecCapturedSourceEvidenceV1, ...] = ()
    original: OriginalIssuerEvidenceV1 | None = None
    integrity: SecIntegrityEvidenceV1 | None = None
    primary_media_type: str | None = None
    failure_evidence: ArtifactRefV1 | None = None
    issue_codes: tuple[str, ...] = ()
    retryable: bool = False

    @model_validator(mode="after")
    def original_scope(self) -> OriginalValidationEvidenceV1:
        request, original, integrity = self.request, self.original, self.integrity
        if self.issue_codes != tuple(sorted(set(self.issue_codes))):
            raise ValueError("original validation issues must be canonical")
        if tuple(r.uri for r in self.responses) != tuple(
            sorted({r.uri for r in self.responses})
        ) or any(r.scope != request.scope for r in self.responses):
            raise ValueError("original responses must retain the exact capture scope")
        if original is None:
            if (
                not self.issue_codes
                or integrity is not None
                or self.primary_media_type is not None
                or self.captured_sources
            ):
                raise ValueError("failed original validation needs a retained reason")
            return self
        if (
            integrity is None
            or not self.primary_media_type
            or not self.captured_sources
        ):
            raise ValueError("parsed original requires complete integrity evidence")
        report, source, runtime = original.report, original.source, request.runtime
        if (
            self.retryable
            or self.failure_evidence is not None
            or source.cik != request.cik
            or source.accession_number != request.filing.accession_number
            or source.form != request.filing.form
            or source.is_amendment
            or source.available_at != request.filing.accepted_at
            or original.decision_at != request.valuation_timestamp
            or report.taxonomy_cache_hash != runtime.taxonomy_cache_sha256
            or report.taxonomy_version != runtime.taxonomy_version
            or report.parser_version != runtime.arelle_version
            or report.validation_profile_digest != runtime.validation_profile_digest
            or report.validation_profile.profile_id != runtime.validation_profile_id
            or integrity.quality_decision != "pass"
            or integrity.accession_number != source.accession_number
            or integrity.primary_document_uri != source.uri
            or integrity.raw_content_hash != source.content_hash
            or integrity.parser_input_hash != source.parser_input_hash
            or integrity.validation_profile_digest != report.validation_profile_digest
            or integrity.taxonomy_manifest_hash != runtime.taxonomy_cache_sha256
            or integrity.normalized_fact_count != len(report.facts)
            or integrity.normalized_fact_digest != fact_semantic_digest(report)
            or integrity.captured_at != source.captured_at
            or report.blocking_finding_codes()
            or integrity.dqc_filing_context != report.dqc_filing_context
            or report.dqc_filing_context is not None
            and (
                report.dqc_filing_context.issuer_id != request.cik
                or report.dqc_filing_context.accession_number
                != request.filing.accession_number
                or report.dqc_filing_context.filing_date != request.filing.filing_date
            )
            or report.validation_engines != integrity.validation_engines
            or execution_validation_evidence(report) != integrity.validation_evidence
        ):
            raise ValueError("original validation differs from its source/runtime")
        responses = {response.uri: response for response in self.responses}
        for uri, content_hash in (
            (source.uri, source.content_hash),
            (integrity.archive_uri, integrity.archive_hash),
            (integrity.archive_index_uri, integrity.archive_index_hash),
        ):
            response = responses.get(uri)
            if response is None or response.content_hash != content_hash:
                raise ValueError("validated original requires exact retained receipts")
        submission_hashes = set(integrity.submission_content_hashes)
        if submission_hashes:
            submission_uri = (
                integrity.archive_index_uri.rsplit("/", 1)[0]
                + f"/{integrity.accession_number}.txt"
            )
            submission = responses.get(submission_uri)
            if submission is None or submission_hashes != {submission.content_hash}:
                raise ValueError("integrity requires its exact submission receipt")
        require_sec_validation_evidence(report)
        codes = set(original.issue_codes)
        if original.status == "matched" and (
            original.report_period_end != request.filing.report_period_end
        ):
            codes.add("ORIGINAL_CATALOG_PERIOD_MISMATCH")
        if self.issue_codes != tuple(sorted(codes)):
            raise ValueError("original validation decisions cannot be reproduced")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)

    @property
    def artifact_id(self) -> str:
        if self.retryable:
            return f"original-validation-attempt:{self.digest}"
        return f"original-validation:{self.request.digest}"

    @property
    def dependencies(self) -> tuple[str, ...]:
        values = {
            self.request.digest,
            *(r.content_hash for r in self.responses),
            *(sha256_digest(r) for r in self.responses),
            *(s.content_hash for s in self.captured_sources),
        }
        if self.integrity is not None:
            values.update(self.integrity.parser_content_hashes)
        if self.original is not None:
            values.update(
                digest
                for _, _, _, digest, _ in parser_action_markers(
                    (
                        *self.original.report.validation_evidence,
                        *self.original.report.execution_evidence,
                    )
                )
            )
            values.update(
                use
                for _, _, _, _, use in parser_action_markers(
                    (
                        *self.original.report.validation_evidence,
                        *self.original.report.execution_evidence,
                    )
                )
                if use is not None
            )
        if self.failure_evidence is not None:
            values.add(self.failure_evidence.content_hash)
        return tuple(sorted(values))


class OriginalValidationPort(Protocol):
    def validate_original_filing(
        self,
        request: OriginalValidationRequestV1,
        *,
        deadline_at: datetime,
        build_checks: ParserBuildChecks | None = None,
    ) -> OriginalValidationEvidenceV1: ...


class OriginalSecuritySelectionV1(StrictModel):
    ticker: str | None = Field(default=None, pattern=r"^[A-Z0-9][A-Z0-9.-]{0,14}$")
    share_class: str | None = Field(default=None, min_length=1, max_length=512)
    security_selection_policy: OriginalSecuritySelectionPolicy | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    history_identity_policy: OriginalHistoryIdentityPolicy | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class OriginalPreparationRequestV1(OriginalSecuritySelectionV1):
    protocol: Literal["sec-original-preparation-v1"] = "sec-original-preparation-v1"
    annual: ArtifactRefV1
    runtime: OriginalValidationRuntimeV1

    @model_validator(mode="after")
    def annual_reference(self) -> OriginalPreparationRequestV1:
        if (
            self.annual.role != "sec-original-annual-discovery-v1"
            or self.annual.media_type != "application/json"
        ):
            raise ValueError("original preparation requires annual discovery evidence")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)


class OriginalPreparedFilingV1(StrictModel):
    validation: ArtifactRefV1
    identity: IdentityV1 | None
    issue_codes: tuple[str, ...]


class OriginalPreparationEvidenceV1(StrictModel):
    request: OriginalPreparationRequestV1
    filings: tuple[OriginalPreparedFilingV1, ...]
    issue_codes: tuple[str, ...]
    retryable: bool

    @property
    def digest(self) -> str:
        return sha256_digest(self)

    @property
    def artifact_id(self) -> str:
        if self.retryable:
            return f"original-preparation-attempt:{self.digest}"
        return f"original-preparation:{self.request.digest}"

    @property
    def dependencies(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    self.request.digest,
                    self.request.annual.content_hash,
                    *(item.validation.content_hash for item in self.filings),
                }
            )
        )


@dataclass(frozen=True)
class _FilingAssessment:
    request: OriginalValidationRequestV1
    artifact_id: str
    facts: tuple[ParsedXbrlFactV1, ...] | None
    issue_codes: tuple[str, ...]
    retryable: bool

    @classmethod
    def from_validation(
        cls, validation: OriginalValidationEvidenceV1, *, project: bool
    ) -> _FilingAssessment:
        facts = (
            validation.original.report.facts
            if validation.original is not None
            else None
        )
        return cls(
            request=validation.request,
            artifact_id=validation.artifact_id,
            facts=(
                original_identity_evidence_facts(facts)
                if project and facts is not None
                else facts
            ),
            issue_codes=validation.issue_codes,
            retryable=validation.retryable,
        )


class OriginalPreparation:
    def __init__(
        self,
        *,
        discovery: AnnualDiscovery,
        validator: OriginalValidationPort,
        artifacts: EvidenceArtifactStore,
        content: ContentAddressedStore,
        capture_lock: Callable[[str], AbstractContextManager[None]],
        build_checks: ParserBuildChecks | None = None,
    ) -> None:
        self._discovery = discovery
        self._validator = validator
        self._artifacts = artifacts
        self._content = content
        self._lock = capture_lock
        self._build_checks = build_checks

    @contextmanager
    def evidence_operation(self) -> Iterator[OriginalPreparationReads]:
        reads = OriginalPreparationReads(self)
        try:
            yield reads
            reads.finish()
        finally:
            reads.clear()

    def reference(self, artifact_id: str, role: str) -> ArtifactRefV1:
        record = self._artifacts.get(artifact_id)
        return ArtifactRefV1(
            artifact_id=artifact_id,
            content_hash=record.content_hash,
            media_type=record.media_type,
            role=role,
        )

    def _bytes(self, reference: ArtifactRefV1) -> bytes:
        record = self._artifacts.get(reference.artifact_id)
        payload = self._artifacts.read(reference.artifact_id)
        if (
            record.status != "valid"
            or record.retention != "evidence"
            or record.content_hash != reference.content_hash
            or record.media_type != reference.media_type
            or hashlib.sha256(payload).hexdigest() != reference.content_hash
        ):
            raise SnapshotError("ORIGINAL_PREPARATION_INVALID", "artifact differs")
        return payload

    def _annual(
        self, request: OriginalPreparationRequestV1
    ) -> AnnualDiscoveryEvidenceV1:
        self._bytes(request.annual)
        return self._discovery.read(request.annual.artifact_id)

    def read_validation(
        self, artifact_id: str, *, build_checks: ParserBuildChecks | None = None
    ) -> OriginalValidationEvidenceV1:
        reference = self.reference(artifact_id, "sec-original-validation-v1")
        payload = self._bytes(reference)
        original_checks = OriginalIssuerEvidenceChecks()
        try:
            evidence = OriginalValidationEvidenceV1.model_validate_json(
                payload, context=original_checks
            )
        except ValueError as error:
            raise SnapshotError(
                "ORIGINAL_PREPARATION_INVALID", "invalid retained validation"
            ) from error
        record = self._artifacts.get(artifact_id)
        if (
            reference.media_type != "application/json"
            or payload != canonical_bytes(evidence)
            or artifact_id != evidence.artifact_id
            or record.dependency_hashes != evidence.dependencies
        ):
            raise SnapshotError("ORIGINAL_PREPARATION_INVALID", "validation differs")
        request_id = f"original-validation-request:{evidence.request.digest}"
        if self._bytes(
            self.reference(request_id, "original-validation-request-v1")
        ) != (canonical_bytes(evidence.request)):
            raise SnapshotError("ORIGINAL_PREPARATION_INVALID", "request differs")
        for response in evidence.responses:
            receipt_id = sec_response_artifact_id(response.scope, response.uri)
            if self._bytes(
                self.reference(receipt_id, "sec-response-receipt.v1")
            ) != canonical_bytes(response) or self._artifacts.get(
                receipt_id
            ).dependency_hashes != (response.content_hash,):
                raise SnapshotError(
                    "ORIGINAL_PREPARATION_INVALID", "response receipt differs"
                )
        sources = (
            *((s.content_hash, s.media_type) for s in evidence.responses),
            *((s.content_hash, s.media_type) for s in evidence.captured_sources),
        )
        for content_hash, media_type in sources:
            payload = self._content.get(content_hash, media_type=media_type)
            if hashlib.sha256(payload).hexdigest() != content_hash:
                raise SnapshotError("ORIGINAL_PREPARATION_INVALID", "source differs")
        if evidence.integrity is not None:
            if evidence.original is not None:
                require_parser_action_evidence(
                    evidence.original,
                    artifacts=self._artifacts,
                    delivery_revision=evidence.request.runtime.declared_source_revision,
                    original_checks=original_checks,
                    build_checks=build_checks,
                )
            for digest in evidence.integrity.parser_content_hashes:
                payload = self._content.get(
                    digest,
                    media_type="application/json"
                    if evidence.integrity.inline_documents
                    and digest == evidence.integrity.parser_input_hash
                    else evidence.primary_media_type or "application/octet-stream",
                )
                if hashlib.sha256(payload).hexdigest() != digest:
                    raise SnapshotError(
                        "ORIGINAL_PREPARATION_INVALID", "parser input differs"
                    )
        if evidence.failure_evidence is not None:
            self._bytes(evidence.failure_evidence)
        return evidence

    def _completed_validation(
        self, request: OriginalValidationRequestV1, build_checks: ParserBuildChecks
    ) -> OriginalValidationEvidenceV1 | None:
        artifact_id = f"original-validation:{request.digest}"
        try:
            self._artifacts.get(artifact_id)
        except SnapshotError as error:
            if error.code != "ARTIFACT_NOT_FOUND":
                raise
            return None
        evidence = self.read_validation(artifact_id, build_checks=build_checks)
        build_checks.verify()
        if evidence.request != request:
            raise SnapshotError("ORIGINAL_PREPARATION_INVALID", "request differs")
        return evidence

    def _validation(
        self,
        request: OriginalValidationRequestV1,
        deadline_at: datetime,
        build_checks: ParserBuildChecks,
    ) -> OriginalValidationEvidenceV1:
        if completed := self._completed_validation(request, build_checks):
            return completed
        with self._lock(sha256_digest(("original-validation", request.digest))):
            if completed := self._completed_validation(request, build_checks):
                return completed
            self._artifacts.put_with_receipt(
                f"original-validation-request:{request.digest}", request
            )
            evidence = self._validator.validate_original_filing(
                request, deadline_at=deadline_at, build_checks=build_checks
            )
            build_checks.verify()
            if evidence.request != request:
                raise SnapshotError(
                    "ORIGINAL_PREPARATION_INVALID", "validator request differs"
                )
            self._artifacts.put_with_receipt(
                evidence.artifact_id, evidence, evidence.dependencies
            )
            return self.read_validation(evidence.artifact_id, build_checks=build_checks)

    @staticmethod
    def _selection_issues(
        request: OriginalPreparationRequestV1, annual: AnnualDiscoveryEvidenceV1
    ) -> tuple[str, ...]:
        runtime, selection = request.runtime, annual.request
        codes = set(annual.selection.issue_codes)
        if (
            runtime.declared_source_revision != selection.declared_source_revision
            or runtime.supported_filing_years != selection.supported_filing_years
            or runtime.supported_filing_forms != selection.supported_filing_forms
        ):
            codes.add("ORIGINAL_RUNTIME_CATALOG_MISMATCH")
        return tuple(sorted(codes))

    def _assess(
        self,
        request: OriginalPreparationRequestV1,
        annual: AnnualDiscoveryEvidenceV1,
        validations: tuple[OriginalValidationEvidenceV1, ...],
    ) -> OriginalPreparationEvidenceV1:
        return self._assess_filings(
            request,
            annual,
            tuple(
                _FilingAssessment.from_validation(validation, project=False)
                for validation in validations
            ),
        )

    def _assess_filings(
        self,
        request: OriginalPreparationRequestV1,
        annual: AnnualDiscoveryEvidenceV1,
        validations: tuple[_FilingAssessment, ...],
    ) -> OriginalPreparationEvidenceV1:
        codes = set(self._selection_issues(request, annual))
        expected = () if codes else annual.selection.selected
        if tuple(v.request.filing for v in validations) != expected or any(
            v.request.cik != annual.request.cik
            or v.request.valuation_timestamp != annual.request.valuation_timestamp
            or v.request.runtime != request.runtime
            for v in validations
        ):
            raise SnapshotError(
                "ORIGINAL_PREPARATION_INVALID", "selected originals differ"
            )
        filings = []
        for validation in validations:
            identity = None
            reasons = set(validation.issue_codes)
            if not reasons and validation.facts is not None:
                try:
                    identity = resolve_original_filing_identity(
                        cik=validation.request.cik,
                        accepted_at=validation.request.filing.accepted_at,
                        facts=validation.facts,
                        ticker=request.ticker,
                        share_class=request.share_class,
                        security_selection_policy=request.security_selection_policy,
                    )
                except IdentityResolutionError as error:
                    reasons.add(error.code)
            codes.update(reasons)
            filings.append(
                OriginalPreparedFilingV1(
                    validation=self.reference(
                        validation.artifact_id, "sec-original-validation-v1"
                    ),
                    identity=identity,
                    issue_codes=tuple(sorted(reasons)),
                )
            )
        if (
            len(
                {
                    sha256_digest(
                        original_history_identity_key(
                            f.identity, request.history_identity_policy
                        )
                    )
                    for f in filings
                    if f.identity is not None
                }
            )
            > 1
        ):
            codes.add("ORIGINAL_HISTORY_IDENTITY_CONFLICT")
        return OriginalPreparationEvidenceV1(
            request=request,
            filings=tuple(filings),
            issue_codes=tuple(sorted(codes)),
            retryable=annual.retryable or any(v.retryable for v in validations),
        )

    def read(self, artifact_id: str) -> OriginalPreparationEvidenceV1:
        evidence, _ = self.read_with_validations(artifact_id)
        return evidence

    def read_with_validations(
        self, artifact_id: str
    ) -> tuple[OriginalPreparationEvidenceV1, tuple[OriginalValidationEvidenceV1, ...]]:
        """Return preparation and the original validations checked in this read."""
        reference = self.reference(artifact_id, "sec-original-preparation-v1")
        payload = self._bytes(reference)
        try:
            evidence = OriginalPreparationEvidenceV1.model_validate_json(payload)
        except ValueError as error:
            raise SnapshotError(
                "ORIGINAL_PREPARATION_INVALID", "invalid retained preparation"
            ) from error
        request = evidence.request
        annual = self._annual(request)
        build_checks = self._build_checks or ParserBuildChecks()
        validations = tuple(
            self.read_validation(f.validation.artifact_id, build_checks=build_checks)
            for f in evidence.filings
        )
        record = self._artifacts.get(artifact_id)
        if (
            reference.media_type != "application/json"
            or payload != canonical_bytes(evidence)
            or artifact_id != evidence.artifact_id
            or record.dependency_hashes != evidence.dependencies
            or evidence != self._assess(request, annual, validations)
            or self._bytes(
                self.reference(
                    f"original-preparation-request:{request.digest}",
                    "original-preparation-request-v1",
                )
            )
            != canonical_bytes(request)
        ):
            raise SnapshotError("ORIGINAL_PREPARATION_INVALID", "preparation differs")
        return evidence, validations

    def _completed(
        self,
        request: OriginalPreparationRequestV1,
        reads: OriginalPreparationReads | None = None,
    ) -> tuple[OriginalPreparationEvidenceV1, ArtifactPublicationV1] | None:
        artifact_id = f"original-preparation:{request.digest}"
        try:
            record = self._artifacts.get(artifact_id)
        except SnapshotError as error:
            if error.code != "ARTIFACT_NOT_FOUND":
                raise
            return None
        evidence = (
            reads.read(artifact_id)[0] if reads is not None else self.read(artifact_id)
        )
        if evidence.request != request:
            raise SnapshotError("ORIGINAL_PREPARATION_INVALID", "request differs")
        return evidence, ArtifactPublicationV1(artifact=record, wrote=False)

    def execute(
        self,
        request: OriginalPreparationRequestV1,
        *,
        deadline_at: datetime,
        reads: OriginalPreparationReads | None = None,
    ) -> tuple[OriginalPreparationEvidenceV1, ArtifactPublicationV1]:
        if reads is not None and reads.owner is not self:
            raise ValueError("preparation reads belong to a different owner")
        if reads is not None and reads.closed:
            raise RuntimeError("preparation read scope has ended")
        build_checks = reads.builds if reads is not None else ParserBuildChecks()
        request = OriginalPreparationRequestV1.model_validate_json(
            canonical_bytes(request)
        )
        if completed := self._completed(request, reads):
            return completed
        with self._lock(sha256_digest(("original-preparation", request.digest))):
            annual = self._annual(request)
            if completed := self._completed(request, reads):
                return completed
            self._artifacts.put_with_receipt(
                f"original-preparation-request:{request.digest}", request
            )
            validations = tuple(
                _FilingAssessment.from_validation(
                    self._validation(
                        OriginalValidationRequestV1(
                            cik=annual.request.cik,
                            valuation_timestamp=annual.request.valuation_timestamp,
                            filing=filing,
                            runtime=request.runtime,
                        ),
                        deadline_at,
                        build_checks,
                    ),
                    project=True,
                )
                for filing in (
                    ()
                    if self._selection_issues(request, annual)
                    else annual.selection.selected
                )
            )
            evidence = self._assess_filings(request, annual, validations)
            build_checks.verify()
            publication = self._artifacts.put_with_receipt(
                evidence.artifact_id, evidence, evidence.dependencies
            )
            return evidence, publication


class _PreparationReadSetV1(StrictModel):
    records: tuple[ArtifactRecordV1, ...]
    content: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class _CheckedPreparation:
    evidence: OriginalPreparationEvidenceV1
    validations: tuple[OriginalValidationEvidenceV1, ...]
    by_accession: dict[
        str, tuple[OriginalPreparedFilingV1, OriginalValidationEvidenceV1]
    ]
    records: tuple[ArtifactRecordV1, ...]
    content: tuple[tuple[str, str], ...]
    weight: int


class _PreparationReadArtifacts:
    def __init__(self, store: EvidenceArtifactStore) -> None:
        self.store = store
        self.records: dict[str, ArtifactRecordV1] = {}

    def get(self, artifact_id: str) -> ArtifactRecordV1:
        record = self.store.get(artifact_id)
        previous = self.records.setdefault(artifact_id, record)
        if previous != record:
            raise SnapshotError("ORIGINAL_PREPARATION_INVALID", "metadata changed")
        return record

    def read(self, artifact_id: str) -> bytes:
        record = self.get(artifact_id)
        raw = self.store.read(artifact_id)
        if hashlib.sha256(raw).hexdigest() != record.content_hash:
            raise SnapshotError("ORIGINAL_PREPARATION_INVALID", "artifact differs")
        self.get(artifact_id)
        return raw

    def put(
        self,
        artifact_id: str,
        value: object,
        dependency_hashes: tuple[str, ...] = (),
        *,
        media_type: str = "application/json",
        retention: Literal["evidence", "operational_cache"] = "evidence",
    ) -> ArtifactRecordV1:
        return self.put_with_receipt(
            artifact_id,
            value,
            dependency_hashes,
            media_type=media_type,
            retention=retention,
        ).artifact

    def put_with_receipt(
        self,
        artifact_id: str,
        value: object,
        dependency_hashes: tuple[str, ...] = (),
        *,
        media_type: str = "application/json",
        retention: Literal["evidence", "operational_cache"] = "evidence",
    ) -> ArtifactPublicationV1:
        return self.store.put_with_receipt(
            artifact_id,
            value,
            dependency_hashes,
            media_type=media_type,
            retention=retention,
        )

    def put_bytes_with_receipt(
        self,
        artifact_id: str,
        payload: bytes,
        dependency_hashes: tuple[str, ...] = (),
        *,
        media_type: str = "application/octet-stream",
        retention: Literal["evidence", "operational_cache"] = "evidence",
    ) -> ArtifactPublicationV1:
        return self.store.put_bytes_with_receipt(
            artifact_id,
            payload,
            dependency_hashes,
            media_type=media_type,
            retention=retention,
        )


class _PreparationReadContent:
    def __init__(self, store: ContentAddressedStore) -> None:
        self.store = store
        self.reads: set[tuple[str, str]] = set()

    def get(self, content_hash: str, *, media_type: str) -> bytes:
        raw = self.store.get(content_hash, media_type=media_type)
        if hashlib.sha256(raw).hexdigest() != content_hash:
            raise SnapshotError("ORIGINAL_PREPARATION_INVALID", "source differs")
        self.reads.add((content_hash, media_type))
        return raw

    def put(self, content: bytes, *, media_type: str) -> str:
        return self.store.put(content, media_type=media_type)


_Copied = TypeVar("_Copied")


class OriginalPreparationReads:
    """Owner-issued checked preparations for one bounded independent operation.

    Cached models come exclusively from a full owner read of hash-checked bytes.
    Mutable headers are copied on return; only frozen parser reports are shared.
    Metadata is current at each use. Store bytes are checked again at the closing
    boundary; a failed boundary must not be treated as a successful operation.
    Consumed dependency sets are streamed to a temporary journal so eviction never
    drops publication checks or grows the retained model graph. The journal closes
    with the operation. No caller-supplied digest, path, mtime or validation flag
    admits a cache entry.
    """

    def __init__(
        self,
        owner: OriginalPreparation,
        *,
        max_entries: int = 8,
        max_retained_bytes: int = 128 * 1024 * 1024,
    ) -> None:
        if min(max_entries, max_retained_bytes) < 0:
            raise ValueError("preparation retention limits must be nonnegative")
        self.owner = owner
        self.max_entries = max_entries
        self.max_retained_bytes = max_retained_bytes
        self.retained_bytes = 0
        self.entries: OrderedDict[str, _CheckedPreparation] = OrderedDict()
        self.closed = False
        # Stream consumed dependency sets independently of the bounded model cache.
        self._journal = tempfile.TemporaryFile()
        self.builds = ParserBuildChecks()

    def _current(self, entry: _CheckedPreparation | _PreparationReadSetV1) -> None:
        for record in entry.records:
            if self.owner._artifacts.get(record.artifact_id) != record:
                raise SnapshotError("ORIGINAL_PREPARATION_INVALID", "metadata changed")
        self.builds.verify()

    def _read(self, artifact_id: str) -> _CheckedPreparation:
        if self.closed:
            raise RuntimeError("preparation read scope has ended")
        entry = self.entries.get(artifact_id)
        if entry is not None:
            self._current(entry)
            self.entries.move_to_end(artifact_id)
            return entry
        artifacts = _PreparationReadArtifacts(self.owner._artifacts)
        content = _PreparationReadContent(self.owner._content)
        discovery = self.owner._discovery.with_readers(artifacts, content)
        reader = OriginalPreparation(
            discovery=discovery,
            validator=self.owner._validator,
            artifacts=artifacts,
            content=content,
            capture_lock=self.owner._lock,
            build_checks=self.builds,
        )
        evidence, validations = reader.read_with_validations(artifact_id)
        index = {
            validation.request.filing.accession_number: (filing, validation)
            for filing, validation in zip(evidence.filings, validations, strict=True)
        }
        if len(index) != len(validations):
            raise SnapshotError("ORIGINAL_PREPARATION_INVALID", "duplicate accession")
        records = tuple(artifacts.records.values())
        sources = tuple(sorted(content.reads))
        # Charge the reachable Python object graph, including model dictionaries.
        # This bounds retained objects, not transient parsing peaks or allocator RSS.
        weight = _retained_size((evidence, validations, index, records, sources))
        entry = _CheckedPreparation(
            evidence, validations, index, records, sources, weight
        )
        self._current(entry)
        self._journal.seek(0, 2)
        self._journal.write(
            canonical_bytes({"records": records, "content": sources}) + b"\n"
        )
        if self.max_entries and weight <= self.max_retained_bytes:
            while self.entries and (
                len(self.entries) >= self.max_entries
                or self.retained_bytes + weight > self.max_retained_bytes
            ):
                removed = self.entries.popitem(last=False)[1]
                self.retained_bytes -= removed.weight
                self._verify_bytes(removed)
            self.entries[artifact_id] = entry
            self.retained_bytes += weight
        return entry

    @staticmethod
    def _copy(entry: _CheckedPreparation, value: _Copied) -> _Copied:
        # Reports and their nested contracts are frozen. Copy every mutable header
        # without duplicating the large report or exposing the retained models.
        memo = {
            id(v.original.report): v.original.report
            for v in entry.validations
            if v.original is not None
        }
        return deepcopy(value, memo)

    def read(
        self, artifact_id: str
    ) -> tuple[OriginalPreparationEvidenceV1, tuple[OriginalValidationEvidenceV1, ...]]:
        entry = self._read(artifact_id)
        return self._copy(entry, (entry.evidence, entry.validations))

    def filing(
        self, artifact_id: str, accession: str
    ) -> tuple[
        OriginalPreparationEvidenceV1,
        OriginalPreparedFilingV1,
        OriginalValidationEvidenceV1,
    ]:
        entry = self._read(artifact_id)
        selected = entry.by_accession.get(accession)
        if selected is None:
            raise SnapshotError("ORIGINAL_PREPARATION_INVALID", "accession absent")
        return self._copy(entry, (entry.evidence, *selected))

    def _verify_bytes(self, entry: _CheckedPreparation | _PreparationReadSetV1) -> None:
        self._current(entry)
        for record in entry.records:
            raw = self.owner._artifacts.read(record.artifact_id)
            if hashlib.sha256(raw).hexdigest() != record.content_hash:
                raise SnapshotError("ORIGINAL_PREPARATION_INVALID", "artifact differs")
        for content_hash, media_type in entry.content:
            raw = self.owner._content.get(content_hash, media_type=media_type)
            if hashlib.sha256(raw).hexdigest() != content_hash:
                raise SnapshotError("ORIGINAL_PREPARATION_INVALID", "source differs")
        self._current(entry)

    def verify(self) -> None:
        if self.closed:
            raise RuntimeError("preparation read scope has ended")
        self._journal.seek(0)
        for raw in self._journal:
            self._verify_bytes(_PreparationReadSetV1.model_validate_json(raw))
        # No earlier read set may become stale during another set's slow I/O.
        self._journal.seek(0)
        for raw in self._journal:
            self._current(_PreparationReadSetV1.model_validate_json(raw))
        self.builds.verify()

    def finish(self) -> None:
        try:
            self.verify()
        finally:
            self.clear()

    def clear(self) -> None:
        self._journal.close()
        self.entries.clear()
        self.retained_bytes = 0
        self.closed = True


def _retained_size(root: object) -> int:
    """Count an owned evidence graph once, without following class metadata."""
    seen: set[int] = set()
    pending = [root]
    total = 0
    while pending:
        value = pending.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        total += sys.getsizeof(value)
        if isinstance(value, BaseModel):
            pending.extend((value.__dict__, value.__pydantic_fields_set__))
            pending.extend((value.__pydantic_extra__, value.__pydantic_private__))
        elif isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, (tuple, list, set, frozenset)):
            pending.extend(value)
    return total
