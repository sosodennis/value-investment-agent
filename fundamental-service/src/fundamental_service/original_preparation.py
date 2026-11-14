"""Persistent original validation and security selection before source plans."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Literal, Protocol

from pydantic import AwareDatetime, Field, model_validator

from .annual_discovery import AnnualFilingV1
from .annual_discovery_service import AnnualDiscovery, AnnualDiscoveryEvidenceV1
from .arelle_parser import fact_semantic_digest
from .command_artifacts import EvidenceArtifactStore
from .contracts import (
    IdentityV1,
    SecCapturedSourceEvidenceV1,
    SecIntegrityEvidenceV1,
    StrictModel,
)
from .data_releases import ArtifactRefV1
from .issuer_identity import IdentityResolutionError, resolve_original_filing_identity
from .original_issuer import OriginalIssuerEvidenceV1
from .regulatory_validation import require_sec_validation_evidence
from .replay import ArtifactPublicationV1
from .sec_capture import (
    SecCaptureScopeV1,
    SecResponseReceiptV1,
    sec_response_artifact_id,
)
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
            or report.validation_evidence != integrity.validation_evidence
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
            values.update(
                (self.integrity.parser_input_hash, self.integrity.archive_member_hash)
            )
        if self.failure_evidence is not None:
            values.add(self.failure_evidence.content_hash)
        return tuple(sorted(values))


class OriginalValidationPort(Protocol):
    def validate_original_filing(
        self, request: OriginalValidationRequestV1, *, deadline_at: datetime
    ) -> OriginalValidationEvidenceV1: ...


class OriginalSecuritySelectionV1(StrictModel):
    ticker: str | None = Field(default=None, pattern=r"^[A-Z0-9][A-Z0-9.-]{0,14}$")
    share_class: str | None = Field(default=None, min_length=1, max_length=512)


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


class OriginalPreparation:
    def __init__(
        self,
        *,
        discovery: AnnualDiscovery,
        validator: OriginalValidationPort,
        artifacts: EvidenceArtifactStore,
        content: ContentAddressedStore,
        capture_lock: Callable[[str], AbstractContextManager[None]],
    ) -> None:
        self._discovery = discovery
        self._validator = validator
        self._artifacts = artifacts
        self._content = content
        self._lock = capture_lock

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

    def read_validation(self, artifact_id: str) -> OriginalValidationEvidenceV1:
        reference = self.reference(artifact_id, "sec-original-validation-v1")
        payload = self._bytes(reference)
        try:
            evidence = OriginalValidationEvidenceV1.model_validate_json(payload)
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
            for digest in (
                evidence.integrity.parser_input_hash,
                evidence.integrity.archive_member_hash,
            ):
                payload = self._content.get(
                    digest,
                    media_type=evidence.primary_media_type
                    or "application/octet-stream",
                )
                if hashlib.sha256(payload).hexdigest() != digest:
                    raise SnapshotError(
                        "ORIGINAL_PREPARATION_INVALID", "parser input differs"
                    )
        if evidence.failure_evidence is not None:
            self._bytes(evidence.failure_evidence)
        return evidence

    def _validation(
        self, request: OriginalValidationRequestV1, deadline_at: datetime
    ) -> OriginalValidationEvidenceV1:
        with self._lock(sha256_digest(("original-validation", request.digest))):
            artifact_id = f"original-validation:{request.digest}"
            try:
                self._artifacts.get(artifact_id)
            except SnapshotError as error:
                if error.code != "ARTIFACT_NOT_FOUND":
                    raise
            else:
                evidence = self.read_validation(artifact_id)
                if evidence.request != request:
                    raise SnapshotError(
                        "ORIGINAL_PREPARATION_INVALID", "request differs"
                    )
                return evidence
            self._artifacts.put_with_receipt(
                f"original-validation-request:{request.digest}", request
            )
            evidence = self._validator.validate_original_filing(
                request, deadline_at=deadline_at
            )
            if evidence.request != request:
                raise SnapshotError(
                    "ORIGINAL_PREPARATION_INVALID", "validator request differs"
                )
            self._artifacts.put_with_receipt(
                evidence.artifact_id, evidence, evidence.dependencies
            )
            return self.read_validation(evidence.artifact_id)

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
            if not reasons and validation.original is not None:
                try:
                    identity = resolve_original_filing_identity(
                        cik=validation.request.cik,
                        accepted_at=validation.request.filing.accepted_at,
                        facts=validation.original.report.facts,
                        ticker=request.ticker,
                        share_class=request.share_class,
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
            len({sha256_digest(f.identity) for f in filings if f.identity is not None})
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
        validations = tuple(
            self.read_validation(f.validation.artifact_id) for f in evidence.filings
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
        return evidence

    def execute(
        self, request: OriginalPreparationRequestV1, *, deadline_at: datetime
    ) -> tuple[OriginalPreparationEvidenceV1, ArtifactPublicationV1]:
        request = OriginalPreparationRequestV1.model_validate_json(
            canonical_bytes(request)
        )
        with self._lock(sha256_digest(("original-preparation", request.digest))):
            annual = self._annual(request)
            artifact_id = f"original-preparation:{request.digest}"
            try:
                record = self._artifacts.get(artifact_id)
            except SnapshotError as error:
                if error.code != "ARTIFACT_NOT_FOUND":
                    raise
            else:
                evidence = self.read(artifact_id)
                if evidence.request != request:
                    raise SnapshotError(
                        "ORIGINAL_PREPARATION_INVALID", "request differs"
                    )
                return evidence, ArtifactPublicationV1(artifact=record, wrote=False)
            self._artifacts.put_with_receipt(
                f"original-preparation-request:{request.digest}", request
            )
            validations = tuple(
                self._validation(
                    OriginalValidationRequestV1(
                        cik=annual.request.cik,
                        valuation_timestamp=annual.request.valuation_timestamp,
                        filing=filing,
                        runtime=request.runtime,
                    ),
                    deadline_at,
                )
                for filing in (
                    ()
                    if self._selection_issues(request, annual)
                    else annual.selection.selected
                )
            )
            evidence = self._assess(request, annual, validations)
            publication = self._artifacts.put_with_receipt(
                evidence.artifact_id, evidence, evidence.dependencies
            )
            return evidence, publication
