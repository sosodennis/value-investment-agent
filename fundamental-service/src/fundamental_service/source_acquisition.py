"""Authenticated orchestration for versioned, service-owned SEC ingestion."""

from __future__ import annotations

import hashlib
import json
import logging
import platform
import re
from contextlib import contextmanager
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from importlib.metadata import version
from typing import Literal

from lxml import etree, html
from pydantic import BaseModel, ConfigDict, ValidationError

from .arelle_parser import ArelleParserError, ArelleValidationProfileV1, _directory_hash
from .automatic_source_mapping import (
    AutomaticSecIngestionRequestV1,
    AutomaticSourceMappingAuthority,
)
from .contracts import (
    IdentityResolutionRequestV1,
    IdentityResolutionV1,
    IdentitySourceEvidenceV1,
    IssueV1,
    QualityStatus,
    SecFilingSelectorV1,
    SecIngestionRequestV1,
    SecIngestionResponseV1,
    SecIngestionSourceV1,
    SecSourceRequestV1,
    Severity,
    SourceRole,
)
from .data_releases import ArtifactRefV1, DataReleaseError
from .facts import CanonicalFactRepository, CanonicalMappingV1
from .historical_dqc import historical_profile
from .ingestion import SecIngestionService
from .issuer_identity import (
    IdentityResolutionError,
    resolve_issuer_cik,
    resolve_issuer_identity,
)
from .metadata import PostgresArtifactStore, PostgresContentStore, PostgresMetadataStore
from .operations import ServiceError
from .original_preparation import (
    OriginalValidationEvidenceV1,
    OriginalValidationRequestV1,
    OriginalValidationRuntimeV1,
)
from .original_issuer import OriginalOperatingSourceV1, evaluate_original_issuer
from .sec_capture import RetainedSecSourceAdapter, SecCaptureScopeV1, SecCaptureStore
from .sec_submissions import SecRecentFilingsV1, SecSubmissionsV1
from .sec_source import (
    SecEdgarSourceAdapter,
    SecRequestPolicy,
    SecSourceCapturePort,
    SecSourceError,
)
from .serialization import sha256_digest
from .snapshots import (
    CapturedSource,
    ContentAddressedStore,
    SnapshotError,
    SnapshotRepository,
)

IDENTITY_MAPPING_VERSION: Literal["sec-issuer-identity-v1"] = "sec-issuer-identity-v1"
LOGGER = logging.getLogger("fundamental_service")
_SUPPORTED_SEC_FILING_FORMS = frozenset({"10-K", "10-K/A", "10-Q", "10-Q/A"})
_AWARD_PROXY_LOOKBACK_DAYS = 548
_AWARD_PROXY_BASE_FORM = "DEF 14A"
_AWARD_PROXY_COMPANION_FORMS = frozenset({"DEF 14A/A", "DEFA14A", "DEFA14A/A"})


class _SecPayload(BaseModel):
    model_config = ConfigDict(extra="allow")


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
    supported_filing_years: tuple[int, ...]
    supported_filing_forms: tuple[str, ...]
    historical_dqc_dir: Path | None = None
    historical_dqc_sha256: str | None = None

    def __post_init__(self) -> None:
        if (self.historical_dqc_dir is None) != (self.historical_dqc_sha256 is None):
            raise ValueError(
                "historical DQC source and hash must be configured together"
            )
        if self.historical_dqc_dir is not None:
            if not self.historical_dqc_dir.is_dir():
                raise ValueError("pinned historical DQC source is unavailable")
            if _directory_hash(self.historical_dqc_dir) != self.historical_dqc_sha256:
                raise ValueError("pinned historical DQC source hash does not match")
        if (
            not self.supported_filing_years
            or tuple(sorted(set(self.supported_filing_years)))
            != self.supported_filing_years
        ):
            raise ValueError("SEC validation runtime must declare sorted filing years")
        if any(year < 2000 or year > 2100 for year in self.supported_filing_years):
            raise ValueError("SEC validation runtime filing years are invalid")
        if (
            not self.supported_filing_forms
            or tuple(sorted(set(self.supported_filing_forms)))
            != self.supported_filing_forms
            or any(
                form not in _SUPPORTED_SEC_FILING_FORMS
                for form in self.supported_filing_forms
            )
        ):
            raise ValueError("SEC validation runtime filing forms are invalid")
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


def parse_supported_filing_years(value: str | None) -> tuple[int, ...] | None:
    """Decode the deployment's certified SEC filing-year compatibility pin."""
    if value is None or not value.strip():
        return None
    try:
        years = tuple(sorted({int(item.strip()) for item in value.split(",")}))
    except ValueError as error:
        raise ValueError(
            "FUNDAMENTAL_SEC_SUPPORTED_FILING_YEARS must be comma-separated years"
        ) from error
    if not years or any(year < 2000 or year > 2100 for year in years):
        raise ValueError(
            "FUNDAMENTAL_SEC_SUPPORTED_FILING_YEARS contains an invalid year"
        )
    return years


def parse_supported_filing_forms(value: str | None) -> tuple[str, ...] | None:
    """Decode the deployment's certified SEC filing-form compatibility pin."""
    if value is None or not value.strip():
        return None
    forms = tuple(sorted({item.strip() for item in value.split(",") if item.strip()}))
    if not forms or any(form not in _SUPPORTED_SEC_FILING_FORMS for form in forms):
        raise ValueError(
            "FUNDAMENTAL_SEC_SUPPORTED_FILING_FORMS contains an invalid form"
        )
    return forms


@dataclass(frozen=True)
class _SelectedFiling:
    accession_number: str
    form: str
    filing_date: date
    accepted_at: datetime
    primary_document: str
    is_inline_xbrl: bool | None = None

    @property
    def is_amendment(self) -> bool:
        return self.form.endswith("/A")


@dataclass(frozen=True)
class _OriginalPackage:
    index_source: CapturedSource
    submission_source: CapturedSource
    xbrl_entrypoint: str
    dts_filenames: tuple[str, ...]
    archive_filename: str


class SecIdentityResolutionUseCase:
    """Resolve issuer identity from captured SEC evidence owned by the service."""

    def __init__(
        self,
        *,
        adapter: SecSourceCapturePort,
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
        return IdentitySourceEvidenceV1.model_validate(
            {
                "source_id": source.source_id,
                "source_uri": source.uri,
                "content_hash": stored_hash,
                "captured_at": source.captured_at or source.available_at,
                "available_at": source.available_at,
                "media_type": "application/json",
                "byte_count": len(source.content),
            }
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
        adapter: SecSourceCapturePort,
        ingestion: SecIngestionService,
        metadata: PostgresMetadataStore,
        content_store: ContentAddressedStore,
        settings: SecAcquisitionSettings,
        authorized_organizations: frozenset[str],
        capture_store: SecCaptureStore | None = None,
        automatic_mapping_authority: AutomaticSourceMappingAuthority | None = None,
    ) -> None:
        self.adapter = adapter
        self.ingestion = ingestion
        self.metadata = metadata
        self.content_store = content_store
        self.settings = settings
        self.authorized_organizations = authorized_organizations
        self.capture_store = capture_store
        self.automatic_mapping_authority = automatic_mapping_authority

    @staticmethod
    def _canonical_key_payload(request: SecSourceRequestV1) -> dict[str, object]:
        return SecAcquisitionUseCase._canonical_request_payload(request)

    @staticmethod
    def _canonical_request_payload(
        request: SecSourceRequestV1,
    ) -> dict[str, object]:
        payload = request.model_dump(mode="json")
        payload["required_fields"] = sorted(request.required_fields)
        if isinstance(request, SecIngestionRequestV1):
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
        self, request: SecSourceRequestV1
    ) -> ArelleValidationProfileV1:
        return self._profile_for_id(request.validation_profile_id)

    def _profile_for_id(self, profile_id: str) -> ArelleValidationProfileV1:
        historical = historical_profile(profile_id)
        if historical and self.settings.historical_dqc_dir is None:
            raise ServiceError(
                "VALIDATION_RESOURCES_UNAVAILABLE",
                "historical DQC source is not configured",
                status_code=503,
                retryable=False,
            )
        return ArelleValidationProfileV1(
            profile_id=profile_id,
            validation_mode="sec-efm-dqc",
            edgar_plugin_dir=self.settings.edgar_plugin_dir,
            xule_plugin_dir=self.settings.xule_plugin_dir,
            dqc_ruleset_path=self.settings.dqc_ruleset_path,
            edgar_plugin_sha256=self.settings.edgar_plugin_sha256,
            xule_plugin_sha256=self.settings.xule_plugin_sha256,
            dqc_ruleset_sha256=self.settings.dqc_ruleset_sha256,
            dqc_version=historical.dqc_version if historical else "v31.0.3",
            historical_dqc_dir=self.settings.historical_dqc_dir if historical else None,
            historical_dqc_sha256=self.settings.historical_dqc_sha256
            if historical
            else None,
        )

    def _runtime_key_payload(
        self,
        request: SecSourceRequestV1,
        validation_profile: ArelleValidationProfileV1,
    ) -> dict[str, object]:
        payload = self._canonical_request_payload(request)
        payload["runtime_releases"] = {
            "taxonomy_cache_sha256": self.settings.taxonomy_cache_sha256,
            "validation_profile_digest": validation_profile.digest(),
            "supported_filing_years": self.settings.supported_filing_years,
            "supported_filing_forms": self.settings.supported_filing_forms,
        }
        if isinstance(request, AutomaticSecIngestionRequestV1):
            payload["automatic_mapping_authority"] = (
                self._automatic_authority().runtime_pin(request)
            )
        return payload

    def _automatic_authority(self) -> AutomaticSourceMappingAuthority:
        if self.automatic_mapping_authority is None:
            raise ServiceError(
                "MAPPING_AUTOMATIC_AUTHORITY_UNAVAILABLE",
                "automatic source mapping authority is not configured",
                status_code=503,
                retryable=False,
            )
        if (
            self.automatic_mapping_authority.taxonomy_cache_sha256
            != self.settings.taxonomy_cache_sha256
        ):
            raise ServiceError(
                "MAPPING_AUTOMATIC_RUNTIME_MISMATCH",
                "mapping authority and acquisition taxonomy pins differ",
                status_code=422,
                retryable=False,
            )
        return self.automatic_mapping_authority

    def original_validation_runtime(
        self,
        *,
        declared_source_revision: str,
        validation_profile_id: Literal[
            "sec-efm-us-dqc-v31.0.3", "sec-efm-us-dqc-v1.0.0-historical"
        ] = "sec-efm-us-dqc-v31.0.3",
    ) -> OriginalValidationRuntimeV1:
        profile = self._profile_for_id(validation_profile_id)
        if version("arelle-release") != "2.47.4":
            raise ServiceError(
                "ORIGINAL_VALIDATION_RUNTIME_MISMATCH",
                "original validation requires the pinned Arelle runtime",
                status_code=503,
                retryable=False,
            )
        return OriginalValidationRuntimeV1(
            declared_source_revision=declared_source_revision,
            taxonomy_manifest_id=self.settings.taxonomy_manifest_id,
            taxonomy_version=self.settings.taxonomy_version,
            taxonomy_cache_sha256=self.settings.taxonomy_cache_sha256,
            validation_profile_digest=profile.digest(),
            validation_profile_id=validation_profile_id,
            supported_filing_years=self.settings.supported_filing_years,
            supported_filing_forms=self.settings.supported_filing_forms,
            python_version=platform.python_version(),
            pydantic_version=version("pydantic"),
        )

    def validate_original_filing(
        self, request: OriginalValidationRequestV1, *, deadline_at: datetime
    ) -> OriginalValidationEvidenceV1:
        """Validate a frozen catalog original without assuming security identity."""
        if self.capture_store is None:
            raise ServiceError(
                "SEC_CAPTURE_STORE_UNAVAILABLE",
                "original preparation requires persistent capture receipts",
                status_code=503,
                retryable=False,
            )
        runtime = request.runtime
        if runtime != self.original_validation_runtime(
            declared_source_revision=runtime.declared_source_revision,
            validation_profile_id=runtime.validation_profile_id,
        ):
            raise ServiceError(
                "ORIGINAL_VALIDATION_RUNTIME_MISMATCH",
                "original preparation pins differ from the configured runtime",
                status_code=422,
                retryable=False,
            )
        adapter = RetainedSecSourceAdapter(
            self.adapter,
            scope=request.scope,
            receipts=self.capture_store,
            content=self.content_store,
            capture_lock=self._capture_lock,
        )
        try:
            self._require_before_deadline(deadline_at)
            annual = request.filing
            if (
                annual.accepted_at > request.valuation_timestamp
                or annual.filing_date > request.valuation_timestamp.date()
                or annual.filing_date.year not in runtime.supported_filing_years
                or annual.form not in runtime.supported_filing_forms
                or not annual.is_xbrl
            ):
                raise SnapshotError(
                    "ORIGINAL_FILING_NOT_ELIGIBLE",
                    "catalog original is unavailable at the cutoff or unsupported",
                )
            filing = _SelectedFiling(
                accession_number=annual.accession_number,
                form=annual.form,
                filing_date=annual.filing_date,
                accepted_at=annual.accepted_at,
                primary_document=annual.primary_document,
                is_inline_xbrl=annual.is_inline_xbrl,
            )
            package = self._capture_original_package(
                adapter=adapter, cik=request.cik, filing=filing, deadline_at=deadline_at
            )
            captured_at = package.index_source.captured_at
            if captured_at is None:
                raise SnapshotError(
                    "SEC_CAPTURE_IDENTITY_MISMATCH", "missing capture timestamp"
                )
            validated = self.ingestion.validate_filing(
                source_adapter=adapter,
                cik=request.cik,
                accession_number=filing.accession_number,
                primary_document=package.xbrl_entrypoint,
                filing_archive_filename=package.archive_filename,
                filed_at=filing.accepted_at,
                accepted_at=filing.accepted_at,
                captured_at=captured_at,
                taxonomy_manifest_id=runtime.taxonomy_manifest_id,
                taxonomy_version=runtime.taxonomy_version,
                taxonomy_cache_dir=self.settings.taxonomy_cache_dir,
                reference_sources=(package.index_source,),
                submission_source=package.submission_source,
                dts_filenames=package.dts_filenames,
                profile=self._profile_for_id(runtime.validation_profile_id),
                form=filing.form,
                deadline_at=deadline_at,
            )
            if (
                validated.parser_report.taxonomy_cache_hash
                != runtime.taxonomy_cache_sha256
            ):
                raise SnapshotError(
                    "TAXONOMY_PACKAGE_INVALID", "parser taxonomy release differs"
                )
            original = evaluate_original_issuer(
                validated.parser_report,
                source=OriginalOperatingSourceV1(
                    cik=request.cik,
                    accession_number=filing.accession_number,
                    form=filing.form,
                    uri=validated.source.uri,
                    content_hash=validated.integrity_evidence.raw_content_hash,
                    parser_input_hash=validated.integrity_evidence.parser_input_hash,
                    available_at=filing.accepted_at,
                    captured_at=captured_at,
                    http_status=validated.source.http_status,
                ),
                decision_at=request.valuation_timestamp,
            )
            codes = set(original.issue_codes)
            if (
                original.status == "matched"
                and original.report_period_end != annual.report_period_end
            ):
                codes.add("ORIGINAL_CATALOG_PERIOD_MISMATCH")
            return OriginalValidationEvidenceV1(
                request=request,
                responses=adapter.observed_responses,
                captured_sources=validated.captured_sources,
                original=original,
                integrity=validated.integrity_evidence,
                primary_media_type=validated.source.media_type,
                issue_codes=tuple(sorted(codes)),
            )
        except (
            SecSourceError,
            SnapshotError,
            ArelleParserError,
            ServiceError,
        ) as error:
            failure = None
            if isinstance(error, SnapshotError) and error.evidence_ref is not None:
                record = self.capture_store.get(error.evidence_ref)
                failure = ArtifactRefV1(
                    artifact_id=record.artifact_id,
                    content_hash=record.content_hash,
                    media_type=record.media_type,
                    role="sec-original-validation-failure-v1",
                )
            if (
                isinstance(error, ArelleParserError)
                and error.validation_failure is not None
            ):
                record = self.ingestion.audit_store.put(
                    "original-parser-failure:"
                    + sha256_digest(error.validation_failure),
                    error.validation_failure,
                    retention="evidence",
                )
                failure = ArtifactRefV1(
                    artifact_id=record.artifact_id,
                    content_hash=record.content_hash,
                    media_type=record.media_type,
                    role="sec-original-validation-failure-v1",
                )
            retryable = (
                error.code
                in {"PARSER_CONCURRENCY_EXHAUSTED", "PARSER_RESOURCE_EXHAUSTED"}
                if isinstance(error, ArelleParserError)
                else error.retryable
            )
            return OriginalValidationEvidenceV1(
                request=request,
                responses=adapter.observed_responses,
                failure_evidence=failure,
                issue_codes=(error.code,),
                retryable=retryable,
            )

    def retained_acquisition(
        self, request: SecIngestionRequestV1 | AutomaticSecIngestionRequestV1
    ) -> SecIngestionResponseV1 | None:
        """Read a completed exact-runtime acquisition without provider/parser I/O."""
        payload = self._runtime_key_payload(request, self._validation_profile(request))
        return self.metadata.get_sec_ingestion(
            sha256_digest(payload), expected_acquisition_payload=payload
        )

    def execute(
        self,
        request: SecIngestionRequestV1 | AutomaticSecIngestionRequestV1,
        *,
        caller_principal: str,
        organization_id: str,
        correlation_id: str,
        deadline_at: datetime,
        audit_reuse: bool = True,
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
        existing = self.metadata.get_sec_ingestion(
            acquisition_key, expected_acquisition_payload=key_payload
        )
        if existing is not None:
            return self._reuse_response(
                existing,
                acquisition_key=acquisition_key,
                caller_principal=caller_principal,
                organization_id=organization_id,
                correlation_id=correlation_id,
                audit_reuse=audit_reuse,
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
                return self._reuse_response(
                    existing,
                    acquisition_key=acquisition_key,
                    caller_principal=caller_principal,
                    organization_id=organization_id,
                    correlation_id=correlation_id,
                    audit_reuse=audit_reuse,
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
                resource_failure = error.code in {
                    "PARSER_CONCURRENCY_EXHAUSTED",
                    "PARSER_RESOURCE_EXHAUSTED",
                }
                raise ServiceError(
                    error.code,
                    str(error),
                    status_code=503 if resource_failure else 422,
                    retryable=resource_failure,
                    retry_after_ms=1000 if resource_failure else None,
                ) from error
            except DataReleaseError as error:
                self.metadata.publish_source_audit(
                    acquisition_key=acquisition_key,
                    caller_principal=caller_principal,
                    organization_id=organization_id,
                    correlation_id=correlation_id,
                    source_hashes=(),
                    outcome=error.code,
                )
                raise ServiceError(
                    error.code, str(error), status_code=422, retryable=False
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

    def _reuse_response(
        self,
        existing: SecIngestionResponseV1,
        *,
        acquisition_key: str,
        caller_principal: str,
        organization_id: str,
        correlation_id: str,
        audit_reuse: bool,
    ) -> SecIngestionResponseV1:
        if audit_reuse:
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

    @contextmanager
    def _capture_lock(self, key: str) -> Iterator[None]:
        lease = self.metadata.try_acquire_ingestion_lock(key)
        if lease is None:
            raise SecSourceError(
                "SEC_CAPTURE_IN_PROGRESS",
                "identical SEC response capture is in progress",
                retryable=True,
            )
        try:
            yield
        finally:
            self.metadata.release_ingestion_lock(lease)

    def _acquire_and_publish(
        self,
        request: SecIngestionRequestV1 | AutomaticSecIngestionRequestV1,
        *,
        acquisition_key: str,
        key_payload: dict[str, object],
        caller_principal: str,
        organization_id: str,
        correlation_id: str,
        deadline_at: datetime,
        validation_profile: ArelleValidationProfileV1,
    ) -> SecIngestionResponseV1:
        mapping_resolver = (
            self._automatic_authority().resolver_for(request)
            if isinstance(request, AutomaticSecIngestionRequestV1)
            else None
        )
        adapter = self.adapter
        if (
            self.capture_store is not None
            and request.filing.accession_number is not None
        ):
            adapter = RetainedSecSourceAdapter(
                adapter,
                scope=SecCaptureScopeV1(
                    cik=request.cik,
                    accession_number=request.filing.accession_number,
                    valuation_timestamp=request.valuation_timestamp,
                    source_profile=request.source_selection_policy,
                ),
                receipts=self.capture_store,
                content=self.content_store,
                capture_lock=self._capture_lock,
            )
        submissions_source = adapter.capture_submissions(
            request.cik, deadline_at=deadline_at
        )
        submissions_source = replace(
            submissions_source,
            role=SourceRole.ACQUISITION,
        )
        self.content_store.put(
            submissions_source.content, media_type=submissions_source.media_type
        )
        submissions = self._decode_submissions(submissions_source.content, request)
        filing = self._select_filing(
            submissions,
            request.filing,
            request.valuation_timestamp,
            supported_filing_years=self.settings.supported_filing_years,
            supported_filing_forms=self.settings.supported_filing_forms,
        )
        supplemental_sources, supplemental_issues = self._capture_award_proxy_sources(
            request,
            submissions,
            annual_accession=filing.accession_number,
            deadline_at=deadline_at,
        )
        if self.capture_store is not None and not isinstance(
            adapter, RetainedSecSourceAdapter
        ):
            adapter = RetainedSecSourceAdapter(
                adapter,
                scope=SecCaptureScopeV1(
                    cik=request.cik,
                    accession_number=filing.accession_number,
                    valuation_timestamp=request.valuation_timestamp,
                    source_profile=request.source_selection_policy,
                ),
                receipts=self.capture_store,
                content=self.content_store,
                capture_lock=self._capture_lock,
            )
        package = self._capture_original_package(
            adapter=adapter, cik=request.cik, filing=filing, deadline_at=deadline_at
        )
        index_source = package.index_source
        submission_source = package.submission_source
        xbrl_entrypoint = package.xbrl_entrypoint
        dts_filenames = package.dts_filenames
        filing_archive_filename = package.archive_filename
        mappings = (
            self._resolve_mappings(request, correlation_id=correlation_id)
            if isinstance(request, SecIngestionRequestV1)
            else ()
        )
        captured_at = (
            max(
                item.captured_at or item.available_at
                for item in (submissions_source, index_source, *supplemental_sources)
            )
            if isinstance(adapter, RetainedSecSourceAdapter)
            else datetime.now(UTC)
        )
        preparation = self.ingestion.prepare_filing(
            source_adapter=adapter,
            identity=request.identity,
            identity_basis=request.identity_basis,
            identity_ticker=request.ticker,
            cik=request.cik,
            accession_number=filing.accession_number,
            primary_document=xbrl_entrypoint,
            filing_archive_filename=filing_archive_filename,
            filed_at=filing.accepted_at,
            accepted_at=filing.accepted_at,
            captured_at=captured_at,
            valuation_timestamp=request.valuation_timestamp,
            fiscal_period_selector=request.fiscal_period_selector,
            parser_version=request.parser_version,
            policy_version=request.policy_version,
            taxonomy_manifest_id=request.taxonomy_manifest_id,
            taxonomy_version=request.taxonomy_version,
            acquisition_key=acquisition_key,
            taxonomy_cache_dir=self.settings.taxonomy_cache_dir,
            mappings=mappings,
            mapping_resolver=mapping_resolver,
            reference_sources=(
                submissions_source,
                index_source,
                *supplemental_sources,
            ),
            additional_issues=supplemental_issues,
            submission_source=submission_source,
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
        status: Literal["created", "degraded", "abstain"]
        if required_missing:
            issue_codes.add("REQUIRED_FACTS_UNAVAILABLE")
            status = "abstain"
            quality = QualityStatus.ABSTAIN
        elif (
            not set(request.required_fields) <= verified_fields
            or preparation.snapshot.coverage_status is not QualityStatus.VERIFIED
        ):
            status = "degraded"
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
            identity_evidence_ref=preparation.identity_evidence_ref,
            mapping_evidence_ref=preparation.mapping_evidence_ref,
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

    def _capture_original_package(
        self,
        *,
        adapter: SecSourceCapturePort,
        cik: str,
        filing: _SelectedFiling,
        deadline_at: datetime,
    ) -> _OriginalPackage:
        index_source = adapter.capture_filing_index(
            cik=cik,
            accession_number=filing.accession_number,
            deadline_at=deadline_at,
        )
        submission_source = adapter.capture_filing_submission(
            cik=cik,
            accession_number=filing.accession_number,
            filed_at=filing.accepted_at,
            accepted_at=filing.accepted_at,
            filing_date=filing.filing_date,
            form=filing.form,
            is_amendment=filing.is_amendment,
            amendment_scope="unknown" if filing.is_amendment else None,
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
        xbrl_entrypoint = self._select_xbrl_entrypoint(
            index_source.content,
            filing.primary_document,
            is_inline_xbrl=filing.is_inline_xbrl,
        )
        schema_filename = None
        if Path(xbrl_entrypoint).suffix.lower() in {".htm", ".html", ".xhtml"}:
            primary_source = adapter.capture_filing(
                cik=cik,
                accession_number=filing.accession_number,
                primary_document=xbrl_entrypoint,
                filed_at=filing.accepted_at,
                accepted_at=filing.accepted_at,
                form=filing.form,
                is_amendment=filing.is_amendment,
                amendment_scope="unknown" if filing.is_amendment else None,
                deadline_at=deadline_at,
            )
            schema_filename = self._inline_schema_filename(primary_source.content)
        dts_filenames = self._select_dts_filenames(
            index_source.content, xbrl_entrypoint, schema_filename=schema_filename
        )
        filing_archive_filename = self._select_filing_archive_filename(
            index_source.content, filing.accession_number
        )
        return _OriginalPackage(
            index_source=index_source,
            submission_source=submission_source,
            xbrl_entrypoint=xbrl_entrypoint,
            dts_filenames=dts_filenames,
            archive_filename=filing_archive_filename,
        )

    def _resolve_mappings(
        self, request: SecIngestionRequestV1, *, correlation_id: str
    ) -> tuple[CanonicalMappingV1, ...]:
        mappings = []
        for index, reference in enumerate(request.mappings):
            try:
                mapping = self.metadata.get_mapping(reference.decision_id)
            except SnapshotError as error:
                LOGGER.warning(
                    "fundamental_mapping_error %s",
                    json.dumps(
                        {
                            "correlation_id": correlation_id,
                            "error_code": "FACT_MAPPING_UNRESOLVED",
                            "field_path": f"mappings[{index}]",
                            "normalized_field": reference.normalized_field,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                )
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
                LOGGER.warning(
                    "fundamental_mapping_error %s",
                    json.dumps(
                        {
                            "correlation_id": correlation_id,
                            "error_code": "FACT_MAPPING_UNRESOLVED",
                            "field_path": f"mappings[{index}]",
                            "normalized_field": reference.normalized_field,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                )
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
        payload: bytes, request: SecSourceRequestV1
    ) -> SecSubmissionsV1:
        try:
            submissions = SecSubmissionsV1.model_validate_json(payload)
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
        if request.identity_basis == "current-sec-ticker-v1" and request.ticker not in {
            item.upper() for item in submissions.tickers
        }:
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
        if submissions.filings.recent.isInlineXBRL is not None:
            lengths.add(len(submissions.filings.recent.isInlineXBRL))
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
        submissions: SecSubmissionsV1,
        selector: SecFilingSelectorV1,
        valuation_timestamp: datetime,
        *,
        supported_filing_years: tuple[int, ...],
        supported_filing_forms: tuple[str, ...],
    ) -> _SelectedFiling:
        recent = submissions.filings.recent
        cutoff_date = valuation_timestamp.date() - timedelta(
            days=selector.lookback_days
        )
        eligible = []
        incompatible_count = 0
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
            if filing_date.year not in supported_filing_years:
                incompatible_count += 1
                if selector.accession_number:
                    raise ServiceError(
                        "FILING_RUNTIME_INCOMPATIBLE",
                        "requested SEC filing is outside the installed "
                        "validation runtime",
                        status_code=422,
                        retryable=False,
                    )
                continue
            if form not in supported_filing_forms:
                incompatible_count += 1
                if selector.accession_number:
                    raise ServiceError(
                        "FILING_RUNTIME_INCOMPATIBLE",
                        "requested SEC filing is outside the installed "
                        "validation runtime",
                        status_code=422,
                        retryable=False,
                    )
                continue
            inline_flags = recent.isInlineXBRL
            is_inline_xbrl = None
            if inline_flags is not None:
                inline_flag = str(inline_flags[index]).lower()
                if inline_flag not in {"0", "1", "false", "true"}:
                    raise ServiceError(
                        "FILING_METADATA_INVALID",
                        "SEC inline XBRL indicator is invalid",
                        status_code=502,
                        retryable=False,
                    )
                is_inline_xbrl = inline_flag in {"1", "true"}
            eligible.append(
                _SelectedFiling(
                    accession_number=accession,
                    form=form,
                    filing_date=filing_date,
                    accepted_at=accepted_at.astimezone(UTC),
                    primary_document=recent.primaryDocument[index],
                    is_inline_xbrl=is_inline_xbrl,
                )
            )
        if not eligible:
            if incompatible_count:
                raise ServiceError(
                    "FILING_RUNTIME_INCOMPATIBLE",
                    "no eligible SEC filing matches the installed validation runtime",
                    status_code=422,
                    retryable=False,
                )
            raise ServiceError(
                "FILING_NOT_AVAILABLE_AS_OF",
                "no eligible SEC filing is available at the requested cutoff",
                status_code=422,
                retryable=False,
            )
        return max(eligible, key=lambda item: (item.accepted_at, item.accession_number))

    @staticmethod
    def _select_award_proxy_filings(
        submissions: SecSubmissionsV1,
        valuation_timestamp: datetime,
        *,
        history_rows: tuple[SecRecentFilingsV1, ...] = (),
    ) -> tuple[tuple[_SelectedFiling, ...], tuple[IssueV1, ...]]:
        row_sets = (submissions.filings.recent, *history_rows)
        recent = SecRecentFilingsV1(
            accessionNumber=[
                value for rows in row_sets for value in rows.accessionNumber
            ],
            filingDate=[value for rows in row_sets for value in rows.filingDate],
            acceptanceDateTime=[
                value for rows in row_sets for value in rows.acceptanceDateTime
            ],
            form=[value for rows in row_sets for value in rows.form],
            primaryDocument=[
                value for rows in row_sets for value in rows.primaryDocument
            ],
            isXBRL=[value for rows in row_sets for value in rows.isXBRL],
        )
        cutoff_date = valuation_timestamp.date() - timedelta(
            days=_AWARD_PROXY_LOOKBACK_DAYS
        )
        eligible: list[_SelectedFiling] = []
        for index, form in enumerate(recent.form):
            if (
                form != _AWARD_PROXY_BASE_FORM
                and form not in _AWARD_PROXY_COMPANION_FORMS
            ):
                continue
            try:
                filing_date = date.fromisoformat(recent.filingDate[index])
                if (
                    filing_date < cutoff_date
                    or filing_date > valuation_timestamp.date()
                ):
                    continue
                accession = recent.accessionNumber[index]
                accepted_raw = recent.acceptanceDateTime[index]
                if accepted_raw is None:
                    raise ValueError("acceptanceDateTime is missing")
                accepted_at = datetime.fromisoformat(
                    accepted_raw.replace("Z", "+00:00")
                )
                primary_document = recent.primaryDocument[index]
            except (IndexError, ValueError) as error:
                raise ServiceError(
                    "FILING_METADATA_INVALID",
                    "SEC proxy filing metadata is incomplete or invalid",
                    status_code=502,
                    retryable=False,
                ) from error
            if (
                not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession)
                or not re.fullmatch(r"[A-Za-z0-9_.-]{1,200}", primary_document)
                or accepted_at.tzinfo is None
            ):
                raise ServiceError(
                    "FILING_METADATA_INVALID",
                    "SEC proxy filing metadata is incomplete or invalid",
                    status_code=502,
                    retryable=False,
                )
            if accepted_at > valuation_timestamp:
                continue
            eligible.append(
                _SelectedFiling(
                    accession_number=accession,
                    form=form,
                    filing_date=filing_date,
                    accepted_at=accepted_at.astimezone(UTC),
                    primary_document=primary_document,
                )
            )

        unique: dict[str, _SelectedFiling] = {}
        for item in eligible:
            previous = unique.setdefault(item.accession_number, item)
            if previous != item:
                raise ServiceError(
                    "FILING_METADATA_CONFLICT",
                    "SEC filing indexes disagree on proxy accession metadata",
                    status_code=502,
                    retryable=False,
                )
        eligible = list(unique.values())
        originals = [item for item in eligible if item.form == _AWARD_PROXY_BASE_FORM]
        if not originals:
            return (), (
                IssueV1(
                    code="EQUITY_AWARD_PROXY_UNAVAILABLE",
                    severity=Severity.WARNING,
                    message=(
                        "no definitive proxy original is available within the "
                        "versioned award-source lookback"
                    ),
                ),
            )
        original = max(
            originals, key=lambda item: (item.accepted_at, item.accession_number)
        )
        companions = sorted(
            (
                item
                for item in eligible
                if item.form in _AWARD_PROXY_COMPANION_FORMS
                and item.accepted_at >= original.accepted_at
            ),
            key=lambda item: (item.accepted_at, item.accession_number),
        )
        selected = (original, *companions)
        if len({item.accession_number for item in selected}) != len(selected):
            raise ServiceError(
                "FILING_METADATA_INVALID",
                "SEC proxy submissions repeat an accession",
                status_code=502,
                retryable=False,
            )
        if len(selected) > 12:
            raise ServiceError(
                "SEC_SUPPLEMENTAL_SOURCE_LIMIT",
                "SEC proxy source set exceeds the bounded filing limit",
                status_code=422,
                retryable=False,
            )
        return selected, ()

    def _capture_award_proxy_sources(
        self,
        request: SecSourceRequestV1,
        submissions: SecSubmissionsV1,
        *,
        annual_accession: str,
        deadline_at: datetime,
    ) -> tuple[tuple[CapturedSource, ...], tuple[IssueV1, ...]]:
        if request.supplemental_filing_policy is None:
            return (), ()
        sources: list[CapturedSource] = []
        history_rows: tuple[SecRecentFilingsV1, ...] = ()
        if request.supplemental_filing_policy == "sec-equity-award-proxy.v2":
            history_sources, history_rows = self._capture_award_proxy_history(
                request,
                submissions,
                annual_accession=annual_accession,
                deadline_at=deadline_at,
            )
            sources.extend(history_sources)
        selected, issues = self._select_award_proxy_filings(
            submissions, request.valuation_timestamp, history_rows=history_rows
        )
        if not selected:
            return tuple(sources), issues

        for filing in selected:
            adapter: SecSourceCapturePort = self.adapter
            if self.capture_store is not None:
                delegate = (
                    self.adapter._delegate
                    if isinstance(self.adapter, RetainedSecSourceAdapter)
                    else self.adapter
                )
                adapter = RetainedSecSourceAdapter(
                    delegate,
                    scope=SecCaptureScopeV1(
                        cik=request.cik,
                        accession_number=filing.accession_number,
                        valuation_timestamp=request.valuation_timestamp,
                        source_profile=(
                            f"{request.source_selection_policy}+"
                            f"{request.supplemental_filing_policy}"
                        ),
                    ),
                    receipts=self.capture_store,
                    content=self.content_store,
                    capture_lock=self._capture_lock,
                )
            index = adapter.capture_filing_index(
                cik=request.cik,
                accession_number=filing.accession_number,
                filed_at=filing.accepted_at,
                deadline_at=deadline_at,
            )
            try:
                names = [
                    item.name
                    for item in _FilingIndex.model_validate_json(
                        index.content
                    ).directory.item
                ]
            except ValidationError as error:
                raise ServiceError(
                    "SOURCE_PAYLOAD_INVALID",
                    "SEC proxy filing index response is invalid",
                    status_code=502,
                    retryable=False,
                ) from error
            if names.count(filing.primary_document) != 1:
                raise ServiceError(
                    "FILING_INDEX_ENTRY_MISMATCH",
                    "SEC proxy primary document is not uniquely listed in its accession",
                    status_code=502,
                    retryable=False,
                )
            sources.append(
                replace(
                    index,
                    source_id="sec-supplemental-filing-index",
                    available_at=filing.accepted_at,
                    publication_at=filing.accepted_at,
                    accession_number=filing.accession_number,
                    form=filing.form,
                    filing_date=filing.filing_date,
                    filed_at=filing.accepted_at,
                    filing_version=filing.accession_number,
                    is_amendment=filing.is_amendment,
                    amendment_scope="unknown" if filing.is_amendment else None,
                )
            )
            source = adapter.capture_filing(
                cik=request.cik,
                accession_number=filing.accession_number,
                primary_document=filing.primary_document,
                filed_at=filing.accepted_at,
                accepted_at=filing.accepted_at,
                filing_date=filing.filing_date,
                form=filing.form,
                is_amendment=filing.is_amendment,
                amendment_scope="unknown" if filing.is_amendment else None,
                deadline_at=deadline_at,
            )
            sources.append(replace(source, source_id="sec-supplemental-filing"))
        return tuple(sources), issues

    def _capture_award_proxy_history(
        self,
        request: SecSourceRequestV1,
        submissions: SecSubmissionsV1,
        *,
        annual_accession: str,
        deadline_at: datetime,
    ) -> tuple[tuple[CapturedSource, ...], tuple[SecRecentFilingsV1, ...]]:
        cutoff = request.valuation_timestamp.date() - timedelta(
            days=_AWARD_PROXY_LOOKBACK_DAYS
        )
        try:
            recent_dates = tuple(
                date.fromisoformat(value)
                for value in submissions.filings.recent.filingDate
            )
        except ValueError as error:
            raise ServiceError(
                "SOURCE_PAYLOAD_INVALID",
                "SEC recent filing dates are invalid",
                status_code=502,
                retryable=False,
            ) from error
        references = submissions.filings.files
        if references is None:
            if recent_dates and min(recent_dates) <= cutoff:
                return (), ()
            raise ServiceError(
                "EQUITY_AWARD_PROXY_HISTORY_INCOMPLETE",
                "SEC recent filings do not cover the award-source window and the history index is missing",
                status_code=502,
                retryable=False,
            )
        if len({item.name for item in references}) != len(references) or any(
            not item.name.startswith(f"CIK{request.cik}-")
            or item.filingFrom > item.filingTo
            for item in references
        ):
            raise ServiceError(
                "SOURCE_PAYLOAD_INVALID",
                "SEC historical filing index has duplicate, foreign or reversed entries",
                status_code=502,
                retryable=False,
            )
        overlapping = sorted(
            (
                item
                for item in references
                if item.filingTo >= cutoff
                and item.filingFrom <= request.valuation_timestamp.date()
            ),
            key=lambda item: (item.filingFrom, item.filingTo, item.name),
        )
        if len(overlapping) > 12:
            raise ServiceError(
                "SEC_SUPPLEMENTAL_SOURCE_LIMIT",
                "SEC award-source window exceeds the pinned historical shard limit",
                status_code=422,
                retryable=False,
            )
        adapter: SecSourceCapturePort = self.adapter
        if self.capture_store is not None:
            delegate = (
                self.adapter._delegate
                if isinstance(self.adapter, RetainedSecSourceAdapter)
                else self.adapter
            )
            adapter = RetainedSecSourceAdapter(
                delegate,
                scope=SecCaptureScopeV1(
                    cik=request.cik,
                    accession_number=annual_accession,
                    valuation_timestamp=request.valuation_timestamp,
                    source_profile=(
                        f"{request.source_selection_policy}+{request.supplemental_filing_policy}"
                    ),
                ),
                receipts=self.capture_store,
                content=self.content_store,
                capture_lock=self._capture_lock,
            )
        sources: list[CapturedSource] = []
        rows: list[SecRecentFilingsV1] = []
        for reference in overlapping:
            source = adapter.capture_submission_history(
                cik=request.cik, filename=reference.name, deadline_at=deadline_at
            )
            try:
                history = SecRecentFilingsV1.model_validate_json(source.content)
                lengths = {
                    len(history.accessionNumber),
                    len(history.filingDate),
                    len(history.acceptanceDateTime),
                    len(history.form),
                    len(history.primaryDocument),
                    len(history.isXBRL),
                }
                if history.isInlineXBRL is not None:
                    lengths.add(len(history.isInlineXBRL))
                dates = tuple(date.fromisoformat(value) for value in history.filingDate)
                if (
                    lengths != {reference.filingCount}
                    or not dates
                    or min(dates) != reference.filingFrom
                    or max(dates) != reference.filingTo
                    or len(set(history.accessionNumber)) != reference.filingCount
                ):
                    raise ValueError("history shard differs from the SEC index")
            except (ValidationError, ValueError) as error:
                raise ServiceError(
                    "EQUITY_AWARD_PROXY_HISTORY_INCOMPLETE",
                    "SEC historical filing shard does not match its indexed rows and dates",
                    status_code=502,
                    retryable=False,
                ) from error
            sources.append(source)
            rows.append(history)
        return tuple(sources), tuple(rows)

    def _select_xbrl_entrypoint(
        self,
        payload: bytes,
        primary_document: str,
        *,
        is_inline_xbrl: bool | None,
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
        names = [item.name for item in filing_index.directory.item]
        if is_inline_xbrl is not False:
            candidates = [primary_document]
        else:
            candidates = [
                name
                for name in names
                if name.endswith(".xml")
                and not name.endswith(self._DTS_LINKBASE_SUFFIXES)
                and f"{Path(name).stem}.xsd" in names
            ]
            if primary_document.endswith(".xml"):
                candidates = [name for name in candidates if name == primary_document]
        if (
            len(candidates) != 1
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,200}", candidates[0])
            or names.count(candidates[0]) != 1
            or (
                is_inline_xbrl is False
                and names.count(f"{Path(candidates[0]).stem}.xsd") != 1
            )
            or (
                is_inline_xbrl is True
                and Path(candidates[0]).suffix.lower()
                not in {".htm", ".html", ".xhtml"}
            )
        ):
            raise ServiceError(
                "XBRL_ENTRYPOINT_UNRESOLVED",
                "SEC filing does not identify one indexed XBRL entrypoint",
                status_code=422,
                retryable=False,
            )
        return candidates[0]

    @staticmethod
    def _inline_schema_filename(content: bytes) -> str:
        def namespace(element: etree._Element, prefix: str) -> str | None:
            for ancestor in (element, *element.iterancestors()):
                value = ancestor.get(f"xmlns:{prefix}")
                if value is not None:
                    return value
            return None

        references = []
        try:
            document = html.fromstring(content, parser=html.HTMLParser(no_network=True))
            for element in document.iter():
                if not isinstance(element.tag, str):
                    continue
                prefix, separator, local_name = element.tag.partition(":")
                if (
                    not separator
                    or local_name != "schemaref"
                    or namespace(element, prefix) != "http://www.xbrl.org/2003/linkbase"
                ):
                    continue
                if any(
                    ancestor.get("xml:base") is not None
                    for ancestor in (element, *element.iterancestors())
                ):
                    raise ValueError("schemaRef must use the accession base URI")
                hrefs = [
                    value
                    for name, value in element.attrib.items()
                    if name.endswith(":href")
                    and namespace(element, name.partition(":")[0])
                    == "http://www.w3.org/1999/xlink"
                ]
                if len(hrefs) != 1:
                    raise ValueError("schemaRef requires one bound href")
                references.append(hrefs[0])
        except (etree.ParserError, ValueError):
            references = []
        if len(references) != 1 or not re.fullmatch(
            r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,195}\.xsd", references[0]
        ):
            raise ServiceError(
                "XBRL_SCHEMA_UNRESOLVED",
                "inline SEC original must reference one local taxonomy schema",
                status_code=422,
                retryable=False,
            )
        return references[0]

    def _select_dts_filenames(
        self,
        payload: bytes,
        primary_document: str,
        *,
        schema_filename: str | None = None,
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
        schema_filename = schema_filename or f"{Path(primary_document).stem}.xsd"
        if [item.name for item in filing_index.directory.item].count(
            schema_filename
        ) != 1:
            raise ServiceError(
                "SOURCE_PAYLOAD_INVALID",
                "SEC filing index must contain the primary taxonomy schema exactly once",
                status_code=502,
                retryable=False,
            )
        filing_stem = Path(schema_filename).stem
        expected_names = {
            f"{filing_stem}.xsd",
            *(f"{filing_stem}{suffix}" for suffix in self._DTS_LINKBASE_SUFFIXES),
        }
        selected_sizes: dict[str, int] = {}
        for item in filing_index.directory.item:
            filename = item.name
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
    content_store: PostgresContentStore,
    snapshot_repository: SnapshotRepository,
    fact_repository: CanonicalFactRepository,
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
    supported_filing_years: tuple[int, ...] | None,
    supported_filing_forms: tuple[str, ...] | None,
    authorized_organizations: frozenset[str],
    historical_dqc_dir: str | None = None,
    historical_dqc_sha256: str | None = None,
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
        supported_filing_years,
        supported_filing_forms,
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
        supported_filing_years=supported_filing_years or (),
        supported_filing_forms=supported_filing_forms or (),
        historical_dqc_dir=Path(historical_dqc_dir) if historical_dqc_dir else None,
        historical_dqc_sha256=historical_dqc_sha256,
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
        capture_store=PostgresArtifactStore(metadata, content_store),
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
