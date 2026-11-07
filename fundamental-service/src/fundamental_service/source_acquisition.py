"""Authenticated orchestration for versioned, service-owned SEC ingestion."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .arelle_parser import ArelleParserError, ArelleValidationProfileV1, _directory_hash
from .contracts import (
    IdentityResolutionRequestV1,
    IdentityResolutionV1,
    IdentitySourceEvidenceV1,
    QualityStatus,
    SecFilingSelectorV1,
    SecIngestionRequestV1,
    SecIngestionResponseV1,
    SecIngestionSourceV1,
    SourceRole,
)
from .facts import CanonicalMappingV1
from .ingestion import SecIngestionService
from .issuer_identity import (
    IdentityResolutionError,
    resolve_issuer_cik,
    resolve_issuer_identity,
)
from .metadata import PostgresArtifactStore, PostgresMetadataStore
from .operations import ServiceError
from .sec_source import SecEdgarSourceAdapter, SecRequestPolicy, SecSourceError
from .serialization import sha256_digest
from .snapshots import CapturedSource, ContentAddressedStore, SnapshotError

IDENTITY_MAPPING_VERSION = "sec-issuer-identity-v1"


class _SecPayload(BaseModel):
    model_config = ConfigDict(extra="allow")


class _RecentFilings(_SecPayload):
    accessionNumber: list[str]
    filingDate: list[str]
    acceptanceDateTime: list[str | None]
    form: list[str]
    primaryDocument: list[str]
    isXBRL: list[int | str]


class _SecFilings(_SecPayload):
    recent: _RecentFilings


class _Submissions(_SecPayload):
    cik: int | str
    tickers: list[str] = Field(default_factory=list)
    filings: _SecFilings


class _FilingIndexItem(_SecPayload):
    name: str
    type: str | None = None
    size: int | str


class _FilingIndexDirectory(_SecPayload):
    item: list[_FilingIndexItem]


class _FilingIndex(_SecPayload):
    directory: _FilingIndexDirectory


@dataclass(frozen=True)
class SecAcquisitionSettings:
    taxonomy_cache_dir: Path
    taxonomy_manifest_id: str
    taxonomy_version: str
    taxonomy_cache_sha256: str
    edgar_plugin_dir: Path
    xule_plugin_dir: Path
    dqc_ruleset_path: Path
    edgar_plugin_sha256: str
    xule_plugin_sha256: str
    dqc_ruleset_sha256: str

    def __post_init__(self) -> None:
        if not self.taxonomy_cache_dir.is_dir():
            raise ValueError("pinned SEC taxonomy cache is unavailable")
        if _directory_hash(self.taxonomy_cache_dir) != self.taxonomy_cache_sha256:
            raise ValueError("pinned SEC taxonomy cache hash does not match")
        if not self.edgar_plugin_dir.is_dir():
            raise ValueError("pinned EDGAR validation plugin is unavailable")
        if not self.xule_plugin_dir.is_dir():
            raise ValueError("pinned XULE validation plugin is unavailable")
        if not self.dqc_ruleset_path.is_file():
            raise ValueError("pinned DQC ruleset is unavailable")
        if _directory_hash(self.edgar_plugin_dir) != self.edgar_plugin_sha256:
            raise ValueError("pinned EDGAR validation plugin hash does not match")
        if _directory_hash(self.xule_plugin_dir) != self.xule_plugin_sha256:
            raise ValueError("pinned XULE validation plugin hash does not match")
        if (
            hashlib.sha256(self.dqc_ruleset_path.read_bytes()).hexdigest()
            != self.dqc_ruleset_sha256
        ):
            raise ValueError("pinned DQC ruleset hash does not match")


@dataclass(frozen=True)
class _SelectedFiling:
    accession_number: str
    form: str
    filing_date: date
    accepted_at: datetime
    primary_document: str

    @property
    def is_amendment(self) -> bool:
        return self.form.endswith("/A")


class SecIdentityResolutionUseCase:
    """Resolve issuer identity from captured SEC evidence owned by the service."""

    def __init__(
        self,
        *,
        adapter: SecEdgarSourceAdapter,
        metadata: PostgresMetadataStore,
        content_store: ContentAddressedStore,
        authorized_organizations: frozenset[str],
    ) -> None:
        self.adapter = adapter
        self.metadata = metadata
        self.content_store = content_store
        self.authorized_organizations = authorized_organizations

    def _audit(
        self,
        *,
        request: IdentityResolutionRequestV1,
        caller_principal: str,
        organization_id: str,
        correlation_id: str,
        sources: list[CapturedSource],
        outcome: str,
    ) -> None:
        acquisition_key = sha256_digest(
            {
                "operation": "resolve-issuer-identity",
                "ticker": request.ticker,
                "mapping_version": IDENTITY_MAPPING_VERSION,
            }
        )
        self.metadata.publish_source_audit(
            acquisition_key=acquisition_key,
            caller_principal=caller_principal,
            organization_id=organization_id,
            correlation_id=correlation_id,
            source_hashes=tuple(
                sorted(hashlib.sha256(source.content).hexdigest() for source in sources)
            ),
            outcome=outcome,
        )

    def _store_source(self, source: CapturedSource) -> IdentitySourceEvidenceV1:
        media_type = source.media_type.split(";", maxsplit=1)[0].strip().lower()
        if source.http_status != 200 or media_type != "application/json":
            raise IdentityResolutionError(
                "ISSUER_IDENTITY_SOURCE_INVALID",
                "SEC issuer source response has an unsupported representation",
                status_code=502,
            )
        expected_hash = hashlib.sha256(source.content).hexdigest()
        stored_hash = self.content_store.put(
            source.content, media_type="application/json"
        )
        if stored_hash != expected_hash:
            raise SnapshotError(
                "SOURCE_HASH_MISMATCH",
                "SEC issuer source bytes do not match the content address",
            )
        return IdentitySourceEvidenceV1(
            source_id=source.source_id,
            source_uri=source.uri,
            content_hash=stored_hash,
            captured_at=source.captured_at or source.available_at,
            available_at=source.available_at,
            media_type="application/json",
            byte_count=len(source.content),
        )

    def execute(
        self,
        request: IdentityResolutionRequestV1,
        *,
        caller_principal: str,
        organization_id: str,
        correlation_id: str,
        deadline_at: datetime,
    ) -> IdentityResolutionV1:
        captured: list[CapturedSource] = []
        if organization_id not in self.authorized_organizations:
            self._audit(
                request=request,
                caller_principal=caller_principal,
                organization_id=organization_id,
                correlation_id=correlation_id,
                sources=captured,
                outcome="IDENTITY_RESOLUTION_NOT_AUTHORIZED",
            )
            raise ServiceError(
                "IDENTITY_RESOLUTION_NOT_AUTHORIZED",
                "organization is not authorized for SEC identity resolution",
                status_code=403,
                retryable=False,
            )

        try:
            ticker_source = self.adapter.capture_company_tickers(
                deadline_at=deadline_at
            )
            captured.append(ticker_source)
            ticker_evidence = self._store_source(ticker_source)
            ticker_directory = json.loads(ticker_source.content)
            cik = resolve_issuer_cik(request, ticker_directory=ticker_directory)

            submissions_source = self.adapter.capture_submissions(
                cik, deadline_at=deadline_at
            )
            captured.append(submissions_source)
            submissions_evidence = self._store_source(submissions_source)
            submissions = json.loads(submissions_source.content)

            facts_source = self.adapter.capture_company_facts(
                cik, deadline_at=deadline_at
            )
            captured.append(facts_source)
            facts_evidence = self._store_source(facts_source)
            companyfacts = json.loads(facts_source.content)

            identity = resolve_issuer_identity(
                request,
                ticker_directory=ticker_directory,
                submissions=submissions,
                companyfacts=companyfacts,
            )
            source_evidence = (
                ticker_evidence,
                submissions_evidence,
                facts_evidence,
            )
            digest_payload = {
                "ticker": request.ticker,
                "identity": identity.model_dump(mode="json"),
                "mapping_version": IDENTITY_MAPPING_VERSION,
                "source_evidence": [
                    source.model_dump(mode="json") for source in source_evidence
                ],
            }
            result = IdentityResolutionV1(
                ticker=request.ticker,
                identity=identity,
                mapping_version=IDENTITY_MAPPING_VERSION,
                source_evidence=source_evidence,
                resolution_digest=sha256_digest(digest_payload),
            )
            self._audit(
                request=request,
                caller_principal=caller_principal,
                organization_id=organization_id,
                correlation_id=correlation_id,
                sources=captured,
                outcome="identity-resolved",
            )
            return result
        except IdentityResolutionError as error:
            self._audit(
                request=request,
                caller_principal=caller_principal,
                organization_id=organization_id,
                correlation_id=correlation_id,
                sources=captured,
                outcome=error.code,
            )
            raise ServiceError(
                error.code,
                str(error),
                status_code=error.status_code,
                retryable=False,
            ) from error
        except SecSourceError as error:
            self._audit(
                request=request,
                caller_principal=caller_principal,
                organization_id=organization_id,
                correlation_id=correlation_id,
                sources=captured,
                outcome=error.code,
            )
            if error.code == "REQUEST_DEADLINE_EXCEEDED":
                raise ServiceError(
                    error.code,
                    "SEC identity resolution exceeded its request deadline",
                    status_code=408,
                    retryable=True,
                ) from error
            if error.code == "SOURCE_RATE_LIMITED":
                raise ServiceError(
                    "ISSUER_IDENTITY_SOURCE_RATE_LIMITED",
                    "SEC identity source is temporarily rate limited",
                    status_code=429,
                    retryable=True,
                    retry_after_ms=1000,
                ) from error
            raise ServiceError(
                "ISSUER_IDENTITY_SOURCE_UNAVAILABLE",
                "SEC issuer evidence is temporarily unavailable",
                status_code=503,
                retryable=error.retryable,
            ) from error
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            self._audit(
                request=request,
                caller_principal=caller_principal,
                organization_id=organization_id,
                correlation_id=correlation_id,
                sources=captured,
                outcome="ISSUER_IDENTITY_SOURCE_INVALID",
            )
            raise ServiceError(
                "ISSUER_IDENTITY_SOURCE_INVALID",
                "SEC issuer evidence is not valid JSON",
                status_code=502,
                retryable=False,
            ) from error
        except SnapshotError as error:
            self._audit(
                request=request,
                caller_principal=caller_principal,
                organization_id=organization_id,
                correlation_id=correlation_id,
                sources=captured,
                outcome=error.code,
            )
            raise ServiceError(
                "ISSUER_IDENTITY_EVIDENCE_UNAVAILABLE",
                "SEC issuer evidence could not be stored immutably",
                status_code=503,
                retryable=True,
            ) from error


class SecAcquisitionUseCase:
    """Capture, parse, and atomically publish one canonical SEC acquisition."""

    _DTS_LINKBASE_SUFFIXES = ("_cal.xml", "_def.xml", "_lab.xml", "_pre.xml")
    _MAX_DTS_FILES = 5
    _MAX_DTS_FILE_BYTES = 12_000_000
    _MAX_DTS_TOTAL_BYTES = 48_000_000
    _MAX_ARCHIVE_BYTES = 24_000_000

    def __init__(
        self,
        *,
        adapter: SecEdgarSourceAdapter,
        ingestion: SecIngestionService,
        metadata: PostgresMetadataStore,
        content_store: ContentAddressedStore,
        settings: SecAcquisitionSettings,
        authorized_organizations: frozenset[str],
    ) -> None:
        self.adapter = adapter
        self.ingestion = ingestion
        self.metadata = metadata
        self.content_store = content_store
        self.settings = settings
        self.authorized_organizations = authorized_organizations

    @staticmethod
    def _canonical_key_payload(request: SecIngestionRequestV1) -> dict[str, object]:
        return SecAcquisitionUseCase._canonical_request_payload(request)

    @staticmethod
    def _canonical_request_payload(
        request: SecIngestionRequestV1,
    ) -> dict[str, object]:
        payload = request.model_dump(mode="json")
        payload["required_fields"] = sorted(request.required_fields)
        payload["mappings"] = [
            item.model_dump(mode="json")
            for item in sorted(
                request.mappings, key=lambda mapping: mapping.normalized_field
            )
        ]
        filing = dict(payload["filing"])
        filing["forms"] = sorted(request.filing.forms)
        payload["filing"] = filing
        return payload

    def _validation_profile(
        self, request: SecIngestionRequestV1
    ) -> ArelleValidationProfileV1:
        return ArelleValidationProfileV1(
            profile_id=request.validation_profile_id,
            validation_mode="sec-efm-dqc",
            edgar_plugin_dir=self.settings.edgar_plugin_dir,
            xule_plugin_dir=self.settings.xule_plugin_dir,
            dqc_ruleset_path=self.settings.dqc_ruleset_path,
            edgar_plugin_sha256=self.settings.edgar_plugin_sha256,
            xule_plugin_sha256=self.settings.xule_plugin_sha256,
            dqc_ruleset_sha256=self.settings.dqc_ruleset_sha256,
        )

    def _runtime_key_payload(
        self,
        request: SecIngestionRequestV1,
        validation_profile: ArelleValidationProfileV1,
    ) -> dict[str, object]:
        payload = self._canonical_request_payload(request)
        payload["runtime_releases"] = {
            "taxonomy_cache_sha256": self.settings.taxonomy_cache_sha256,
            "validation_profile_digest": validation_profile.digest(),
        }
        return payload

    def execute(
        self,
        request: SecIngestionRequestV1,
        *,
        caller_principal: str,
        organization_id: str,
        correlation_id: str,
        deadline_at: datetime,
    ) -> SecIngestionResponseV1:
        validation_profile = self._validation_profile(request)
        key_payload = self._runtime_key_payload(request, validation_profile)
        acquisition_key = sha256_digest(key_payload)
        if organization_id not in self.authorized_organizations:
            self.metadata.publish_source_audit(
                acquisition_key=acquisition_key,
                caller_principal=caller_principal,
                organization_id=organization_id,
                correlation_id=correlation_id,
                source_hashes=(),
                outcome="INGESTION_NOT_AUTHORIZED",
            )
            raise ServiceError(
                "INGESTION_NOT_AUTHORIZED",
                "organization is not authorized for SEC data acquisition",
                status_code=403,
                retryable=False,
            )
        if (
            request.taxonomy_manifest_id != self.settings.taxonomy_manifest_id
            or request.taxonomy_version != self.settings.taxonomy_version
        ):
            self.metadata.publish_source_audit(
                acquisition_key=acquisition_key,
                caller_principal=caller_principal,
                organization_id=organization_id,
                correlation_id=correlation_id,
                source_hashes=(),
                outcome="TAXONOMY_PACKAGE_INVALID",
            )
            raise ServiceError(
                "TAXONOMY_PACKAGE_INVALID",
                "requested taxonomy release is not installed",
                status_code=422,
                retryable=False,
            )
        lease = self.metadata.try_acquire_ingestion_lock(acquisition_key)
        if lease is None:
            self.metadata.publish_source_audit(
                acquisition_key=acquisition_key,
                caller_principal=caller_principal,
                organization_id=organization_id,
                correlation_id=correlation_id,
                source_hashes=(),
                outcome="INGESTION_IN_PROGRESS",
            )
            raise ServiceError(
                "INGESTION_IN_PROGRESS",
                "an identical SEC acquisition is already in progress",
                status_code=409,
                retryable=True,
                retry_after_ms=1000,
            )
        try:
            existing = self.metadata.get_sec_ingestion(
                acquisition_key,
                expected_acquisition_payload=key_payload,
            )
            if existing is not None:
                self.metadata.publish_source_audit(
                    acquisition_key=acquisition_key,
                    caller_principal=caller_principal,
                    organization_id=organization_id,
                    correlation_id=correlation_id,
                    source_hashes=tuple(
                        sorted(item.content_hash for item in existing.source_evidence)
                    ),
                    outcome="reused",
                )
                return existing.model_copy(
                    update={
                        "status": "reused",
                        "reused": True,
                        "correlation_id": correlation_id,
                    }
                )
            self._require_before_deadline(deadline_at)
            try:
                result = self._acquire_and_publish(
                    request,
                    acquisition_key=acquisition_key,
                    key_payload=key_payload,
                    caller_principal=caller_principal,
                    organization_id=organization_id,
                    correlation_id=correlation_id,
                    deadline_at=deadline_at,
                    validation_profile=validation_profile,
                )
                self.metadata.publish_source_audit(
                    acquisition_key=acquisition_key,
                    caller_principal=caller_principal,
                    organization_id=organization_id,
                    correlation_id=correlation_id,
                    source_hashes=tuple(
                        sorted(item.content_hash for item in result.source_evidence)
                    ),
                    outcome=result.status,
                )
                return result
            except ServiceError:
                self.metadata.publish_source_audit(
                    acquisition_key=acquisition_key,
                    caller_principal=caller_principal,
                    organization_id=organization_id,
                    correlation_id=correlation_id,
                    source_hashes=(),
                    outcome="failed",
                )
                raise
            except SecSourceError as error:
                self.metadata.publish_source_audit(
                    acquisition_key=acquisition_key,
                    caller_principal=caller_principal,
                    organization_id=organization_id,
                    correlation_id=correlation_id,
                    source_hashes=(),
                    outcome=error.code,
                )
                status_code = 429 if error.code == "SOURCE_RATE_LIMITED" else 503
                raise ServiceError(
                    error.code,
                    error.message,
                    status_code=status_code,
                    retryable=error.retryable,
                    retry_after_ms=1000
                    if error.code == "SOURCE_RATE_LIMITED"
                    else None,
                ) from error
            except ArelleParserError as error:
                self.metadata.publish_source_audit(
                    acquisition_key=acquisition_key,
                    caller_principal=caller_principal,
                    organization_id=organization_id,
                    correlation_id=correlation_id,
                    source_hashes=(),
                    outcome=error.code,
                )
                raise ServiceError(
                    error.code,
                    str(error),
                    status_code=422,
                    retryable=False,
                ) from error
            except SnapshotError as error:
                self.metadata.publish_source_audit(
                    acquisition_key=acquisition_key,
                    caller_principal=caller_principal,
                    organization_id=organization_id,
                    correlation_id=correlation_id,
                    source_hashes=(),
                    outcome=error.code,
                )
                raise ServiceError(
                    error.code,
                    error.message,
                    status_code=422,
                    retryable=error.retryable,
                ) from error
        finally:
            self.metadata.release_ingestion_lock(lease)

    def _acquire_and_publish(
        self,
        request: SecIngestionRequestV1,
        *,
        acquisition_key: str,
        key_payload: dict[str, object],
        caller_principal: str,
        organization_id: str,
        correlation_id: str,
        deadline_at: datetime,
        validation_profile: ArelleValidationProfileV1,
    ) -> SecIngestionResponseV1:
        submissions_source = self.adapter.capture_submissions(
            request.cik, deadline_at=deadline_at
        )
        submissions_source = replace(
            submissions_source,
            role=SourceRole.ACQUISITION,
        )
        submissions_hash = self.content_store.put(
            submissions_source.content, media_type=submissions_source.media_type
        )
        submissions = self._decode_submissions(submissions_source.content, request)
        filing = self._select_filing(
            submissions, request.filing, request.valuation_timestamp
        )
        index_source = self.adapter.capture_filing_index(
            cik=request.cik,
            accession_number=filing.accession_number,
            deadline_at=deadline_at,
        )
        index_source = replace(
            index_source,
            available_at=filing.accepted_at,
            publication_at=filing.accepted_at,
            filed_at=filing.accepted_at,
            accession_number=filing.accession_number,
            form=filing.form,
            filing_version=filing.accession_number,
            is_amendment=filing.is_amendment,
            amendment_scope="unknown" if filing.is_amendment else None,
        )
        dts_filenames = self._select_dts_filenames(
            index_source.content, filing.primary_document
        )
        filing_archive_filename = self._select_filing_archive_filename(
            index_source.content, filing.accession_number
        )
        mappings = self._resolve_mappings(request)
        captured_at = datetime.now(UTC)
        preparation = self.ingestion.prepare_filing(
            identity=request.identity,
            cik=request.cik,
            accession_number=filing.accession_number,
            primary_document=filing.primary_document,
            filing_archive_filename=filing_archive_filename,
            filed_at=filing.accepted_at,
            accepted_at=filing.accepted_at,
            captured_at=captured_at,
            valuation_timestamp=request.valuation_timestamp,
            parser_version=request.parser_version,
            policy_version=request.policy_version,
            taxonomy_manifest_id=request.taxonomy_manifest_id,
            taxonomy_version=request.taxonomy_version,
            acquisition_key=acquisition_key,
            taxonomy_cache_dir=self.settings.taxonomy_cache_dir,
            mappings=mappings,
            reference_sources=(submissions_source, index_source),
            dts_filenames=dts_filenames,
            profile=validation_profile,
            form=filing.form,
            is_amendment=filing.is_amendment,
            amendment_scope="unknown" if filing.is_amendment else None,
            deadline_at=deadline_at,
        )
        if (
            preparation.parser_report.taxonomy_cache_hash
            != self.settings.taxonomy_cache_sha256
        ):
            raise ServiceError(
                "TAXONOMY_PACKAGE_INVALID",
                "Arelle parser used a different taxonomy cache release",
                status_code=422,
                retryable=False,
            )
        source_evidence = tuple(
            SecIngestionSourceV1(
                source_id=record.source_id,
                uri=record.uri,
                role=record.role,
                content_hash=record.content_hash,
                accession_number=record.accession_number,
                available_at=record.available_at,
                captured_at=record.captured_at,
                filed_at=record.filed_at,
            )
            for record in preparation.snapshot.source_records
        )
        present_fields = {fact.normalized_field for fact in preparation.facts}
        verified_fields = {
            fact.normalized_field
            for fact in preparation.facts
            if fact.quality is QualityStatus.VERIFIED
        }
        required_missing = tuple(sorted(set(request.required_fields) - present_fields))
        issue_codes = set(preparation.parser_report.finding_codes)
        issue_codes.update(issue.code for issue in preparation.issues)
        if required_missing:
            self.metadata.publish_source_audit(
                acquisition_key=acquisition_key,
                caller_principal=caller_principal,
                organization_id=organization_id,
                correlation_id=correlation_id,
                source_hashes=tuple(
                    sorted(
                        record.content_hash
                        for record in preparation.snapshot.source_records
                    )
                )
                + (submissions_hash,),
                outcome="abstain",
            )
            raise ServiceError(
                "REQUIRED_FACTS_UNAVAILABLE",
                "SEC filing did not provide every requested verified fact",
                status_code=422,
                retryable=False,
            )
        if (
            verified_fields != set(request.required_fields)
            or preparation.snapshot.coverage_status is not QualityStatus.VERIFIED
        ):
            status: Literal["created", "degraded"] = "degraded"
            quality = QualityStatus.PROVISIONAL
        else:
            status = "created"
            quality = preparation.snapshot.coverage_status
        result = SecIngestionResponseV1(
            contract_version="fundamental.v1",
            status=status,
            identity=request.identity,
            valuation_timestamp=request.valuation_timestamp,
            snapshot_id=preparation.snapshot.snapshot_id,
            manifest_digest=preparation.snapshot.manifest_digest,
            canonical_fact_ids=tuple(
                sorted(fact.fact_id for fact in preparation.facts)
            ),
            source_evidence=source_evidence,
            quality_status=quality,
            issue_codes=tuple(sorted(issue_codes)),
            missing_evidence=required_missing,
            parser_version=request.parser_version,
            validation_profile_id=preparation.parser_report.validation_profile.profile_id,
            validation_profile_digest=preparation.parser_report.validation_profile_digest,
            taxonomy_manifest_id=request.taxonomy_manifest_id,
            taxonomy_version=request.taxonomy_version,
            correlation_id=correlation_id,
        )
        self._require_before_deadline(deadline_at)
        return self.metadata.publish_sec_ingestion(
            acquisition_key=acquisition_key,
            acquisition_payload=key_payload,
            snapshot=preparation.snapshot,
            facts=preparation.facts,
            result=result,
            caller_principal=caller_principal,
            organization_id=organization_id,
        )

    def _resolve_mappings(
        self, request: SecIngestionRequestV1
    ) -> tuple[CanonicalMappingV1, ...]:
        mappings = []
        for reference in request.mappings:
            try:
                mapping = self.metadata.get_mapping(reference.decision_id)
            except SnapshotError as error:
                raise ServiceError(
                    "FACT_MAPPING_UNRESOLVED",
                    "requested mapping release is unavailable",
                    status_code=422,
                    retryable=False,
                ) from error
            if (
                mapping.mapping_version != reference.mapping_version
                or mapping.normalized_field != reference.normalized_field
            ):
                raise ServiceError(
                    "FACT_MAPPING_UNRESOLVED",
                    "requested mapping release is unavailable",
                    status_code=422,
                    retryable=False,
                )
            mappings.append(mapping)
        return tuple(mappings)

    @staticmethod
    def _decode_submissions(
        payload: bytes, request: SecIngestionRequestV1
    ) -> _Submissions:
        try:
            submissions = _Submissions.model_validate_json(payload)
        except ValidationError as error:
            raise ServiceError(
                "SOURCE_PAYLOAD_INVALID",
                "SEC submissions response does not match the expected schema",
                status_code=502,
                retryable=False,
            ) from error
        if str(submissions.cik).lstrip("0") != request.cik.lstrip("0"):
            raise ServiceError(
                "IDENTITY_AMBIGUOUS",
                "SEC submissions CIK does not match the requested issuer",
                status_code=422,
                retryable=False,
            )
        if request.ticker not in {item.upper() for item in submissions.tickers}:
            raise ServiceError(
                "IDENTITY_AMBIGUOUS",
                "requested ticker is not registered to the SEC issuer",
                status_code=422,
                retryable=False,
            )
        lengths = {
            len(submissions.filings.recent.accessionNumber),
            len(submissions.filings.recent.filingDate),
            len(submissions.filings.recent.acceptanceDateTime),
            len(submissions.filings.recent.form),
            len(submissions.filings.recent.primaryDocument),
            len(submissions.filings.recent.isXBRL),
        }
        if len(lengths) != 1:
            raise ServiceError(
                "SOURCE_PAYLOAD_INVALID",
                "SEC submissions columns have inconsistent lengths",
                status_code=502,
                retryable=False,
            )
        return submissions

    @staticmethod
    def _select_filing(
        submissions: _Submissions,
        selector: SecFilingSelectorV1,
        valuation_timestamp: datetime,
    ) -> _SelectedFiling:
        recent = submissions.filings.recent
        cutoff_date = valuation_timestamp.date() - timedelta(
            days=selector.lookback_days
        )
        eligible = []
        for index, accession in enumerate(recent.accessionNumber):
            if selector.accession_number and accession != selector.accession_number:
                continue
            form = recent.form[index]
            if form not in selector.forms or str(recent.isXBRL[index]) not in {
                "1",
                "true",
                "True",
            }:
                continue
            try:
                filing_date = date.fromisoformat(recent.filingDate[index])
                accepted_raw = recent.acceptanceDateTime[index]
                if accepted_raw is None:
                    raise ValueError("acceptanceDateTime is missing")
                accepted_at = datetime.fromisoformat(
                    accepted_raw.replace("Z", "+00:00")
                )
            except ValueError as error:
                raise ServiceError(
                    "FILING_METADATA_INVALID",
                    "SEC filing metadata is missing a valid acceptance timestamp",
                    status_code=502,
                    retryable=False,
                ) from error
            if accepted_at.tzinfo is None or accepted_at > valuation_timestamp:
                continue
            if filing_date < cutoff_date:
                continue
            eligible.append(
                _SelectedFiling(
                    accession_number=accession,
                    form=form,
                    filing_date=filing_date,
                    accepted_at=accepted_at.astimezone(UTC),
                    primary_document=recent.primaryDocument[index],
                )
            )
        if not eligible:
            raise ServiceError(
                "FILING_NOT_AVAILABLE_AS_OF",
                "no eligible SEC filing is available at the requested cutoff",
                status_code=422,
                retryable=False,
            )
        return max(eligible, key=lambda item: (item.accepted_at, item.accession_number))

    def _select_dts_filenames(
        self, payload: bytes, primary_document: str
    ) -> tuple[str, ...]:
        try:
            filing_index = _FilingIndex.model_validate_json(payload)
        except ValidationError as error:
            raise ServiceError(
                "SOURCE_PAYLOAD_INVALID",
                "SEC filing index response does not match the expected schema",
                status_code=502,
                retryable=False,
            ) from error
        filing_stem = Path(primary_document).stem.lower()
        expected_names = {
            f"{filing_stem}.xsd",
            *(f"{filing_stem}{suffix}" for suffix in self._DTS_LINKBASE_SUFFIXES),
        }
        selected_sizes: dict[str, int] = {}
        for item in filing_index.directory.item:
            filename = item.name.lower()
            if filename not in expected_names:
                continue
            try:
                size = int(item.size) if str(item.size).strip() else 0
            except (TypeError, ValueError) as error:
                raise ServiceError(
                    "SOURCE_PAYLOAD_INVALID",
                    "SEC filing index contains an invalid resource size",
                    status_code=502,
                    retryable=False,
                ) from error
            if size < 0 or size > self._MAX_DTS_FILE_BYTES:
                raise ServiceError(
                    "INGESTION_BUDGET_EXCEEDED",
                    "SEC filing resource exceeds the supported size",
                    status_code=413,
                    retryable=False,
                )
            prior_size = selected_sizes.get(filename)
            if prior_size is not None and prior_size != size:
                raise ServiceError(
                    "SOURCE_PAYLOAD_INVALID",
                    "SEC filing index repeats a resource with conflicting sizes",
                    status_code=502,
                    retryable=False,
                )
            selected_sizes[filename] = size
        if f"{filing_stem}.xsd" not in selected_sizes:
            raise ServiceError(
                "SOURCE_PAYLOAD_INVALID",
                "SEC filing index does not contain the primary taxonomy schema",
                status_code=502,
                retryable=False,
            )
        selected = sorted(selected_sizes)
        total_bytes = sum(selected_sizes.values())
        if (
            len(selected) > self._MAX_DTS_FILES
            or total_bytes > self._MAX_DTS_TOTAL_BYTES
        ):
            raise ServiceError(
                "INGESTION_BUDGET_EXCEEDED",
                "SEC filing package exceeds the synchronous resource budget",
                status_code=413,
                retryable=False,
            )
        return tuple(selected)

    def _select_filing_archive_filename(
        self, payload: bytes, accession_number: str
    ) -> str:
        try:
            filing_index = _FilingIndex.model_validate_json(payload)
        except ValidationError as error:
            raise ServiceError(
                "SOURCE_PAYLOAD_INVALID",
                "SEC filing index response does not match the expected schema",
                status_code=502,
                retryable=False,
            ) from error
        expected_name = f"{accession_number}-xbrl.zip"
        matches = [
            item for item in filing_index.directory.item if item.name == expected_name
        ]
        if len(matches) != 1:
            raise ServiceError(
                "SOURCE_PAYLOAD_INVALID",
                "SEC filing index does not contain one accession-matched XBRL archive",
                status_code=502,
                retryable=False,
            )
        try:
            size = int(matches[0].size)
        except (TypeError, ValueError) as error:
            raise ServiceError(
                "SOURCE_PAYLOAD_INVALID",
                "SEC filing index contains an invalid XBRL archive size",
                status_code=502,
                retryable=False,
            ) from error
        if size < 1 or size > self._MAX_ARCHIVE_BYTES:
            raise ServiceError(
                "INGESTION_BUDGET_EXCEEDED",
                "SEC XBRL archive exceeds the supported size",
                status_code=413,
                retryable=False,
            )
        return expected_name

    @staticmethod
    def _require_before_deadline(deadline_at: datetime) -> None:
        if datetime.now(UTC) >= deadline_at:
            raise ServiceError(
                "REQUEST_DEADLINE_EXCEEDED",
                "SEC ingestion exceeded its bounded request deadline",
                status_code=408,
                retryable=True,
            )


def build_runtime_sec_acquisition(
    *,
    metadata: PostgresMetadataStore,
    content_store: ContentAddressedStore,
    snapshot_repository: object,
    fact_repository: object,
    service_token: str | None,
    user_agent: str | None,
    taxonomy_cache_dir: str | None,
    taxonomy_manifest_id: str | None,
    taxonomy_version: str | None,
    taxonomy_cache_sha256: str | None,
    edgar_plugin_dir: str | None,
    xule_plugin_dir: str | None,
    dqc_ruleset_path: str | None,
    edgar_plugin_sha256: str | None,
    xule_plugin_sha256: str | None,
    dqc_ruleset_sha256: str | None,
    authorized_organizations: frozenset[str],
) -> SecAcquisitionUseCase | None:
    values = (
        service_token,
        user_agent,
        taxonomy_cache_dir,
        taxonomy_manifest_id,
        taxonomy_version,
        taxonomy_cache_sha256,
        edgar_plugin_dir,
        xule_plugin_dir,
        dqc_ruleset_path,
        edgar_plugin_sha256,
        xule_plugin_sha256,
        dqc_ruleset_sha256,
    )
    if not all(values):
        return None
    settings = SecAcquisitionSettings(
        taxonomy_cache_dir=Path(taxonomy_cache_dir or ""),
        taxonomy_manifest_id=taxonomy_manifest_id or "",
        taxonomy_version=taxonomy_version or "",
        taxonomy_cache_sha256=taxonomy_cache_sha256 or "",
        edgar_plugin_dir=Path(edgar_plugin_dir or ""),
        xule_plugin_dir=Path(xule_plugin_dir or ""),
        dqc_ruleset_path=Path(dqc_ruleset_path or ""),
        edgar_plugin_sha256=edgar_plugin_sha256 or "",
        xule_plugin_sha256=xule_plugin_sha256 or "",
        dqc_ruleset_sha256=dqc_ruleset_sha256 or "",
    )
    adapter = SecEdgarSourceAdapter(
        policy=SecRequestPolicy(user_agent=user_agent or ""),
        request_slot=metadata.reserve_sec_provider_request_slot,
    )
    ingestion = SecIngestionService(
        source_adapter=adapter,
        content_store=content_store,
        snapshot_repository=snapshot_repository,
        audit_store=PostgresArtifactStore(metadata, content_store),
        fact_repository=fact_repository,
    )
    return SecAcquisitionUseCase(
        adapter=adapter,
        ingestion=ingestion,
        metadata=metadata,
        content_store=content_store,
        settings=settings,
        authorized_organizations=authorized_organizations,
    )


def build_runtime_sec_identity_resolution(
    *,
    metadata: PostgresMetadataStore,
    content_store: ContentAddressedStore,
    user_agent: str | None,
    authorized_organizations: frozenset[str],
) -> SecIdentityResolutionUseCase | None:
    """Build SEC identity resolution without requiring parser artifacts."""
    if not user_agent:
        return None
    adapter = SecEdgarSourceAdapter(
        policy=SecRequestPolicy(user_agent=user_agent),
        request_slot=metadata.reserve_sec_provider_request_slot,
    )
    return SecIdentityResolutionUseCase(
        adapter=adapter,
        metadata=metadata,
        content_store=content_store,
        authorized_organizations=authorized_organizations,
    )
