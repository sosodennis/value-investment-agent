"""Service-owned SEC acquisition, offline validation, and gated publication."""

from __future__ import annotations

import tempfile
import zlib
from dataclasses import dataclass, replace
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Literal, Protocol
from zipfile import BadZipFile, ZipFile

from .arelle_parser import (
    ArelleParseReportV1,
    ArelleValidationProfileV1,
    fact_semantic_digest,
    parse_filing_offline,
)
from .contracts import (
    ArelleFindingEvidenceV1,
    CanonicalFactV1,
    IdentityV1,
    IssueV1,
    QualityStatus,
    SecCapturedSourceEvidenceV1,
    SecIngestionRejectionEvidenceV1,
    SecIntegrityEvidenceV1,
    SecIdentityBasis,
    Severity,
    SourceRole,
)
from .facts import (
    CanonicalFactRepository,
    CanonicalMappingV1,
    FactSelection,
    select_fact_groups,
)
from .regulatory_validation import require_sec_validation_evidence
from .issuer_identity import (
    ORIGINAL_IDENTITY_CONCEPTS,
    IdentityResolutionError,
    validate_original_filing_identity,
)
from .ingestion_mapping import IngestionMappingResolverPort, ValidatedOriginalV1
from .original_issuer import OriginalOperatingSourceV1, evaluate_original_issuer
from .replay import ArtifactRecordV1
from .sec_integrity import assess_filing_response, extract_referenced_graphics
from .sec_rebuild import parsed_facts_to_candidates, select_canonical_fact
from .sec_source import SecSourceCapturePort, sec_source_register
from .serialization import sha256_digest
from .snapshots import (
    CapturedSource,
    ContentAddressedStore,
    FiscalPeriodSelectorV1,
    SnapshotBuilder,
    SnapshotError,
    SnapshotRepository,
    SourceSnapshotV1,
)

_MAX_SEC_XBRL_ARCHIVE_BYTES = 24_000_000
_MAX_SEC_XBRL_ARCHIVE_MEMBERS = 4096
_MAX_SEC_XBRL_ARCHIVE_UNCOMPRESSED_BYTES = 256_000_000
_MAX_SEC_XBRL_PRIMARY_BYTES = 24_000_000
_MAX_SEC_XBRL_RESOURCE_BYTES = 12_000_000
_MAX_SEC_XBRL_SELECTED_BYTES = 48_000_000


def _read_sec_xbrl_archive(
    content: bytes, *, primary_document: str, dts_filenames: tuple[str, ...]
) -> dict[str, bytes]:
    """Read only bounded, index-selected root members without extracting paths."""
    if len(content) > _MAX_SEC_XBRL_ARCHIVE_BYTES:
        raise SnapshotError(
            "INGESTION_BUDGET_EXCEEDED", "SEC XBRL archive exceeds the byte limit"
        )
    required = (primary_document, *dts_filenames)
    if len(set(required)) != len(required):
        raise SnapshotError(
            "SOURCE_PAYLOAD_INVALID", "SEC XBRL member selection contains duplicates"
        )
    if any(
        not name or "/" in name or "\\" in name or name in {".", ".."}
        for name in required
    ):
        raise SnapshotError(
            "SOURCE_PAYLOAD_INVALID", "SEC XBRL member path is not a root filename"
        )
    try:
        with ZipFile(BytesIO(content)) as archive:
            infos = archive.infolist()
            if len(infos) > _MAX_SEC_XBRL_ARCHIVE_MEMBERS:
                raise SnapshotError(
                    "INGESTION_BUDGET_EXCEEDED",
                    "SEC XBRL archive contains too many members",
                )
            all_names: set[str] = set()
            selected_infos = {}
            uncompressed_size = 0
            for info in infos:
                if info.filename in all_names:
                    raise SnapshotError(
                        "SOURCE_PAYLOAD_INVALID",
                        "SEC XBRL archive repeats a member name",
                    )
                all_names.add(info.filename)
                uncompressed_size += info.file_size
                if uncompressed_size > _MAX_SEC_XBRL_ARCHIVE_UNCOMPRESSED_BYTES:
                    raise SnapshotError(
                        "INGESTION_BUDGET_EXCEEDED",
                        "SEC XBRL archive exceeds the uncompressed byte limit",
                    )
                if info.filename in required:
                    if info.flag_bits & 0x1:
                        raise SnapshotError(
                            "SOURCE_PAYLOAD_INVALID",
                            "SEC XBRL archive contains an encrypted member",
                        )
                    selected_infos[info.filename] = info
            missing = sorted(set(required) - selected_infos.keys())
            if missing:
                raise SnapshotError(
                    "SOURCE_PAYLOAD_INVALID",
                    "SEC XBRL archive is missing an index-selected member",
                )
            selected_size = 0
            members: dict[str, bytes] = {}
            for filename in required:
                info = selected_infos[filename]
                file_limit = (
                    _MAX_SEC_XBRL_PRIMARY_BYTES
                    if filename == primary_document
                    else _MAX_SEC_XBRL_RESOURCE_BYTES
                )
                if info.file_size > file_limit:
                    raise SnapshotError(
                        "INGESTION_BUDGET_EXCEEDED",
                        "SEC XBRL member exceeds the supported size",
                    )
                selected_size += info.file_size
                if selected_size > _MAX_SEC_XBRL_SELECTED_BYTES:
                    raise SnapshotError(
                        "INGESTION_BUDGET_EXCEEDED",
                        "SEC XBRL selected members exceed the byte limit",
                    )
                member = archive.read(info)
                if len(member) != info.file_size:
                    raise SnapshotError(
                        "SOURCE_PAYLOAD_INVALID",
                        "SEC XBRL member size does not match its directory entry",
                    )
                members[filename] = member
            return members
    except SnapshotError:
        raise
    except (
        BadZipFile,
        EOFError,
        NotImplementedError,
        OSError,
        RuntimeError,
        zlib.error,
    ) as error:
        raise SnapshotError(
            "SOURCE_PAYLOAD_INVALID", "SEC XBRL archive could not be verified"
        ) from error


def _stage_filing_graphics(
    roots: tuple[Path, Path],
    *,
    html_content: bytes,
    archive_content: bytes,
    primary_document: str,
) -> None:
    graphics = extract_referenced_graphics(
        html_content=html_content,
        archive_content=archive_content,
        primary_document=primary_document,
    )
    for relative_path, content in graphics:
        for root in roots:
            resource = root / relative_path
            resource.parent.mkdir(parents=True, exist_ok=True)
            resource.write_bytes(content)


class IngestionAuditStore(Protocol):
    def put(
        self,
        artifact_id: str,
        value: object,
        dependency_hashes: tuple[str, ...] = (),
        *,
        media_type: str = "application/json",
        retention: Literal["evidence", "operational_cache"] = "evidence",
    ) -> ArtifactRecordV1: ...


@dataclass(frozen=True)
class ValidatedSecFiling:
    """Strictly validated original evidence; no identity or snapshot is assumed."""

    source: CapturedSource
    archive_source: CapturedSource
    index_source: CapturedSource
    dts_sources: tuple[CapturedSource, ...]
    captured_sources: tuple[SecCapturedSourceEvidenceV1, ...]
    parser_report: ArelleParseReportV1
    integrity_evidence: SecIntegrityEvidenceV1


@dataclass(frozen=True)
class SecIngestionResult:
    snapshot: SourceSnapshotV1
    parser_report: ArelleParseReportV1
    selection: FactSelection
    integrity_evidence: SecIntegrityEvidenceV1
    facts: tuple[CanonicalFactV1, ...] = ()
    missing_fields: tuple[str, ...] = ()
    issues: tuple[IssueV1, ...] = ()
    identity_evidence_ref: str | None = None
    mapping_evidence_ref: str | None = None


class SecIngestionService:
    """Own SEC acquisition, byte integrity, parser gates, and fact selection."""

    def __init__(
        self,
        *,
        source_adapter: SecSourceCapturePort,
        content_store: ContentAddressedStore,
        snapshot_repository: SnapshotRepository,
        audit_store: IngestionAuditStore,
        fact_repository: CanonicalFactRepository | None = None,
    ) -> None:
        self.source_adapter = source_adapter
        self.content_store = content_store
        self.audit_store = audit_store
        self.fact_repository = fact_repository
        self.builder = SnapshotBuilder(
            content_store, snapshot_repository, sec_source_register()
        )

    def validate_filing(
        self,
        *,
        cik: str,
        accession_number: str,
        primary_document: str,
        filing_archive_filename: str | None = None,
        filed_at: datetime,
        captured_at: datetime,
        taxonomy_manifest_id: str | None,
        taxonomy_version: str,
        taxonomy_cache_dir: Path,
        reference_sources: tuple[CapturedSource, ...] = (),
        submission_source: CapturedSource | None = None,
        accepted_at: datetime | None = None,
        deadline_at: datetime | None = None,
        dts_filenames: tuple[str, ...] = (),
        profile: ArelleValidationProfileV1 | None = None,
        source_adapter: SecSourceCapturePort | None = None,
        form: str = "10-K",
        is_amendment: bool = False,
        amends_accession: str | None = None,
        amendment_scope: str | None = None,
    ) -> ValidatedSecFiling:
        """Validate original bytes and regulatory evidence before identity/publication."""
        adapter = source_adapter or self.source_adapter
        if profile is None:
            raise SnapshotError(
                "VALIDATION_PROFILE_REQUIRED",
                "SEC ingestion requires an explicitly pinned EFM/DQC profile",
            )
        if (
            profile.validation_mode != "sec-efm-dqc"
            or profile.edgar_plugin_dir is None
            or profile.xule_plugin_dir is None
            or profile.dqc_ruleset_path is None
        ):
            raise SnapshotError(
                "SEC_VALIDATION_REQUIRED",
                "SEC ingestion requires the pinned sec-efm-dqc profile",
            )
        if submission_source is not None:
            submission_uri = (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                f"{accession_number.replace('-', '')}/{accession_number}.txt"
            )
            if (
                submission_source.source_id != "sec-filing-submission"
                or submission_source.role is not SourceRole.FILING
                or submission_source.uri != submission_uri
                or submission_source.accession_number != accession_number
                or submission_source.form != form
                or submission_source.is_amendment != is_amendment
                or submission_source.available_at != (accepted_at or filed_at)
                or submission_source.filed_at != filed_at
                or not 200 <= submission_source.http_status < 300
            ):
                raise SnapshotError(
                    "SEC_SUBMISSION_SOURCE_MISMATCH",
                    "full-submission source is not bound to the selected filing",
                )
        index_source = next(
            (
                item
                for item in reference_sources
                if item.source_id == "sec-filing-index"
            ),
            None,
        )
        if index_source is None:
            index_source = adapter.capture_filing_index(
                cik=cik,
                accession_number=accession_number,
                filed_at=accepted_at or filed_at,
                captured_at=captured_at,
                deadline_at=deadline_at,
            )
        else:
            index_source = replace(
                index_source,
                available_at=accepted_at or filed_at,
                publication_at=accepted_at or filed_at,
                accession_number=accession_number,
                form=form,
                filed_at=accepted_at or filed_at,
                filing_version=accession_number,
                is_amendment=is_amendment,
                amendment_scope="unknown" if is_amendment else amendment_scope,
            )
        archive_source = adapter.capture_filing_archive(
            cik=cik,
            accession_number=accession_number,
            filename=filing_archive_filename,
            filed_at=filed_at,
            accepted_at=accepted_at,
            form=form,
            is_amendment=is_amendment,
            amends_accession=amends_accession,
            amendment_scope=amendment_scope,
            deadline_at=deadline_at,
        )
        source = adapter.capture_filing(
            cik=cik,
            accession_number=accession_number,
            primary_document=primary_document,
            filed_at=filed_at,
            captured_at=captured_at,
            form=form,
            is_amendment=is_amendment,
            amends_accession=amends_accession,
            amendment_scope=amendment_scope,
            accepted_at=accepted_at,
            deadline_at=deadline_at,
        )
        members = _read_sec_xbrl_archive(
            archive_source.content,
            primary_document=primary_document,
            dts_filenames=dts_filenames,
        )
        dts_sources = tuple(
            replace(
                archive_source,
                source_id="sec-taxonomy",
                uri=f"{archive_source.uri}#member={filename}",
                role=SourceRole.TAXONOMY,
                content=members[filename],
                media_type="application/xml",
                taxonomy_manifest_id=taxonomy_manifest_id,
            )
            for filename in dts_filenames
        )
        evidence_sources = (
            index_source,
            source,
            archive_source,
            *((submission_source,) if submission_source is not None else ()),
            *dts_sources,
        )
        captured_sources = tuple(
            SecCapturedSourceEvidenceV1(
                source_id=item.source_id,
                uri=item.uri,
                role=item.role,
                media_type=item.media_type,
                http_status=item.http_status,
                available_at=item.available_at,
                captured_at=item.captured_at or item.available_at,
                publication_at=item.publication_at,
                accession_number=item.accession_number,
                form=item.form,
                filed_at=item.filed_at,
                response_headers=item.response_headers,
                declared_size=item.declared_size,
                received_size=(
                    item.received_size
                    if item.received_size is not None
                    else len(item.content)
                ),
                content_hash=self.content_store.put(
                    item.content, media_type=item.media_type
                ),
            )
            for item in evidence_sources
        )
        assessment = assess_filing_response(
            raw_response=source,
            archive_index=index_source,
            archive=archive_source,
        )
        normalized_hash = self.content_store.put(
            assessment.normalized_content, media_type=source.media_type
        )
        archive_member_hash = self.content_store.put(
            assessment.archive_member, media_type=source.media_type
        )
        if normalized_hash != assessment.normalized_content_hash:
            raise SnapshotError(
                "SOURCE_HASH_MISMATCH", "normalized SEC artifact failed hash check"
            )
        with tempfile.TemporaryDirectory(prefix="fundamental-sec-filing-") as directory:
            root = Path(directory)
            normalized_root = root / "normalized"
            archive_root = root / "archive"
            normalized_root.mkdir()
            archive_root.mkdir()
            normalized_path = normalized_root / primary_document
            archive_path = archive_root / primary_document
            normalized_path.write_bytes(assessment.normalized_content)
            archive_path.write_bytes(assessment.archive_member)
            _stage_filing_graphics(
                (normalized_root, archive_root),
                html_content=assessment.normalized_content,
                archive_content=archive_source.content,
                primary_document=primary_document,
            )
            for filename in dts_filenames:
                (normalized_root / filename).write_bytes(members[filename])
                (archive_root / filename).write_bytes(members[filename])
            report = parse_filing_offline(
                normalized_path,
                profile=profile,
                taxonomy_version=taxonomy_version,
                taxonomy_cache_dir=taxonomy_cache_dir,
                source_content_hash=normalized_hash,
                deadline_at=deadline_at,
            )
            require_sec_validation_evidence(report)
            archive_report = report
            if assessment.relation == "normalized":
                archive_report = parse_filing_offline(
                    archive_path,
                    profile=profile,
                    taxonomy_version=taxonomy_version,
                    taxonomy_cache_dir=taxonomy_cache_dir,
                    source_content_hash=archive_member_hash,
                    deadline_at=deadline_at,
                )
                require_sec_validation_evidence(archive_report)
                if fact_semantic_digest(report) != fact_semantic_digest(
                    archive_report
                ) or self._finding_signature(report) != self._finding_signature(
                    archive_report
                ):
                    raise SnapshotError(
                        "NORMALIZATION_SEMANTIC_MISMATCH",
                        "normalized and SEC archive XBRL semantics differ",
                    )

        fact_digest = fact_semantic_digest(report)
        archive_fact_digest = fact_semantic_digest(archive_report)
        blocking_codes = set(report.blocking_finding_codes())
        taxonomy_hash = report.taxonomy_cache_hash
        if taxonomy_hash is None:
            raise SnapshotError(
                "TAXONOMY_MANIFEST_MISSING",
                "offline parser did not produce a taxonomy manifest hash",
            )
        integrity_evidence = SecIntegrityEvidenceV1(
            accession_number=accession_number,
            primary_document_uri=source.uri,
            captured_at=source.captured_at or captured_at,
            archive_index_uri=index_source.uri,
            archive_index_hash=assessment.archive_index_hash,
            declared_primary_size=assessment.declared_primary_size,
            raw_response_headers=source.response_headers,
            raw_received_size=(
                source.received_size
                if source.received_size is not None
                else len(source.content)
            ),
            raw_content_hash=assessment.raw_content_hash,
            declared_response_size=source.declared_size,
            archive_uri=archive_source.uri,
            archive_size=(
                archive_source.received_size
                if archive_source.received_size is not None
                else len(archive_source.content)
            ),
            archive_hash=assessment.archive_hash,
            archive_member_name=assessment.archive_member_name,
            archive_member_size=len(assessment.archive_member),
            archive_member_hash=assessment.archive_member_hash,
            integrity_relation=assessment.relation,
            normalized_content_size=len(assessment.normalized_content),
            normalized_content_hash=normalized_hash,
            normalization_policy_id=assessment.normalization_policy_id,
            normalization_rule_signature=assessment.normalization_rule_signature,
            normalization_reason=assessment.normalization_reason,
            removed_ranges=assessment.removed_ranges,
            normalized_fact_count=len(report.facts),
            normalized_fact_digest=fact_digest,
            archive_fact_count=len(archive_report.facts),
            archive_fact_digest=archive_fact_digest,
            parser_input_hash=report.source_content_hash or "",
            validation_profile_digest=report.validation_profile_digest,
            validation_engines=report.validation_engines,
            validation_evidence=report.validation_evidence,
            network_attempt_count=report.network_attempt_count,
            taxonomy_manifest_hash=taxonomy_hash,
            arelle_version=profile.arelle_version,
            efm_profile=profile.efm_profile,
            dqc_version=profile.dqc_version,
            xule_version=profile.xule_version,
            findings=tuple(
                ArelleFindingEvidenceV1.model_validate(
                    {
                        "code": finding.code,
                        "severity": finding.severity,
                        "blocks": finding.code in blocking_codes,
                        "rule_severity": finding.rule_severity,
                    }
                )
                for finding in report.findings
            ),
            quality_decision="block" if blocking_codes else "pass",
        )
        if blocking_codes:
            rejection = SecIngestionRejectionEvidenceV1(
                contract_version="fundamental.sec-ingestion-rejection.v1",
                error_code="PARSER_VALIDATION_BLOCKED",
                captured_sources=captured_sources,
                integrity_evidence=integrity_evidence,
                parser_replay_digests=tuple(
                    sorted({report.replay_digest(), archive_report.replay_digest()})
                ),
            )
            digest = sha256_digest(rejection)
            accession_id = "".join(
                character
                for character in accession_number
                if character.isascii() and character.isalnum()
            )
            record = self.audit_store.put(
                f"sec-ingestion-rejection-{accession_id}-{digest}",
                rejection,
                tuple(
                    sorted(
                        {
                            *(item.content_hash for item in captured_sources),
                            assessment.normalized_content_hash,
                            assessment.archive_member_hash,
                            report.validation_profile_digest,
                            taxonomy_hash,
                        }
                    )
                ),
                retention="evidence",
            )
            raise SnapshotError(
                "PARSER_VALIDATION_BLOCKED",
                "blocking SEC EFM/DQC findings prevent canonical fact publication",
                evidence_ref=record.artifact_id,
            )
        if not report.facts:
            raise SnapshotError("PARSER_FACTS_MISSING", "Arelle produced no XBRL facts")

        return ValidatedSecFiling(
            source=source,
            archive_source=archive_source,
            index_source=index_source,
            dts_sources=dts_sources,
            captured_sources=captured_sources,
            parser_report=report,
            integrity_evidence=integrity_evidence,
        )

    def prepare_filing(
        self,
        *,
        identity: IdentityV1,
        cik: str,
        accession_number: str,
        primary_document: str,
        filing_archive_filename: str | None = None,
        filed_at: datetime,
        captured_at: datetime,
        valuation_timestamp: datetime,
        fiscal_period_selector: FiscalPeriodSelectorV1 | None = None,
        parser_version: str,
        policy_version: str,
        taxonomy_manifest_id: str | None,
        taxonomy_version: str,
        acquisition_key: str | None = None,
        taxonomy_cache_dir: Path,
        mappings: tuple[CanonicalMappingV1, ...],
        mapping_resolver: IngestionMappingResolverPort | None = None,
        reference_sources: tuple[CapturedSource, ...] = (),
        additional_issues: tuple[IssueV1, ...] = (),
        submission_source: CapturedSource | None = None,
        accepted_at: datetime | None = None,
        deadline_at: datetime | None = None,
        dts_filenames: tuple[str, ...] = (),
        profile: ArelleValidationProfileV1 | None = None,
        source_adapter: SecSourceCapturePort | None = None,
        form: str = "10-K",
        is_amendment: bool = False,
        amends_accession: str | None = None,
        amendment_scope: str | None = None,
        identity_basis: SecIdentityBasis = "current-sec-ticker-v1",
        identity_ticker: str | None = None,
    ) -> SecIngestionResult:
        if mapping_resolver is not None and (
            mappings or identity_basis != "original-filing-dei-v1"
        ):
            raise SnapshotError(
                "MAPPING_RESOLUTION_MODE_INVALID",
                "automatic mapping requires original identity without manual mappings",
            )
        if identity_basis == "original-filing-dei-v1" and (
            form != "10-K" or is_amendment or not identity_ticker or accepted_at is None
        ):
            raise SnapshotError(
                "HISTORICAL_IDENTITY_SCOPE_UNSUPPORTED",
                "original identity requires a pinned original 10-K, acceptance and ticker",
            )
        validated = self.validate_filing(
            cik=cik,
            accession_number=accession_number,
            primary_document=primary_document,
            filing_archive_filename=filing_archive_filename,
            filed_at=filed_at,
            captured_at=captured_at,
            taxonomy_manifest_id=taxonomy_manifest_id,
            taxonomy_version=taxonomy_version,
            taxonomy_cache_dir=taxonomy_cache_dir,
            reference_sources=reference_sources,
            submission_source=submission_source,
            accepted_at=accepted_at,
            deadline_at=deadline_at,
            dts_filenames=dts_filenames,
            profile=profile,
            source_adapter=source_adapter,
            form=form,
            is_amendment=is_amendment,
            amends_accession=amends_accession,
            amendment_scope=amendment_scope,
        )
        source = validated.source
        archive_source = validated.archive_source
        index_source = validated.index_source
        dts_sources = validated.dts_sources
        captured_sources = validated.captured_sources
        report = validated.parser_report
        integrity_evidence = validated.integrity_evidence
        taxonomy_hash = integrity_evidence.taxonomy_manifest_hash
        normalized_hash = integrity_evidence.normalized_content_hash

        identity_evidence_ref = None
        if identity_basis == "original-filing-dei-v1":
            identity_failure = None
            try:
                validate_original_filing_identity(
                    identity,
                    cik=cik,
                    ticker=identity_ticker or "",
                    accepted_at=accepted_at or filed_at,
                    facts=report.facts,
                )
            except IdentityResolutionError as error:
                identity_failure = error
            identity_evidence = {
                "schema_version": "sec-original-identity-evidence.v1",
                "identity_basis": identity_basis,
                "identity": identity,
                "cik": cik,
                "ticker": identity_ticker,
                "accession_number": accession_number,
                "available_at": accepted_at,
                "source_hash": integrity_evidence.raw_content_hash,
                "parser_input_hash": report.source_content_hash,
                "validation_profile_digest": report.validation_profile_digest,
                "parser_replay_digest": report.replay_digest(),
                "facts": tuple(
                    sorted(
                        (
                            f
                            for f in report.facts
                            if f.concept in ORIGINAL_IDENTITY_CONCEPTS
                        ),
                        key=sha256_digest,
                    )
                ),
                "outcome": "refused" if identity_failure else "matched",
                "error_code": identity_failure.code if identity_failure else None,
                "reason": str(identity_failure) if identity_failure else None,
                "current_ticker_or_survival_data_used": False,
            }
            record = self.audit_store.put(
                f"sec-original-identity-{sha256_digest(identity_evidence)}",
                identity_evidence,
                (
                    integrity_evidence.raw_content_hash,
                    normalized_hash,
                    report.validation_profile_digest,
                ),
                retention="evidence",
            )
            identity_evidence_ref = record.artifact_id
            if identity_failure:
                raise SnapshotError(
                    identity_failure.code,
                    str(identity_failure),
                    evidence_ref=identity_evidence_ref,
                ) from identity_failure

        mapping_evidence_ref = None
        mapping_issues: tuple[IssueV1, ...] = ()
        mapping_missing: tuple[str, ...] = ()
        if mapping_resolver is not None:
            original = evaluate_original_issuer(
                report,
                source=OriginalOperatingSourceV1(
                    cik=cik,
                    accession_number=accession_number,
                    uri=source.uri,
                    content_hash=integrity_evidence.raw_content_hash,
                    parser_input_hash=report.source_content_hash or "",
                    form=form,
                    is_amendment=is_amendment,
                    available_at=accepted_at or filed_at,
                    captured_at=source.captured_at or captured_at,
                    http_status=source.http_status,
                ),
                decision_at=valuation_timestamp,
            )
            resolved = mapping_resolver.resolve(
                ValidatedOriginalV1(
                    identity=identity,
                    original=original,
                    integrity=integrity_evidence,
                    captured_sources=captured_sources,
                    primary_media_type=source.media_type,
                )
            )
            mappings = resolved.mappings
            mapping_evidence_ref = resolved.evidence_ref
            mapping_issues = resolved.issues
            mapping_missing = resolved.missing_fields

        other_sources = tuple(
            item for item in reference_sources if item.source_id != "sec-filing-index"
        )
        sources = (
            *other_sources,
            index_source,
            source,
            archive_source,
            *((submission_source,) if submission_source is not None else ()),
            *dts_sources,
        )
        snapshot = self.builder.prepare(
            identity=identity,
            valuation_timestamp=valuation_timestamp,
            fiscal_period_selector=fiscal_period_selector,
            captured_at=captured_at,
            parser_version=parser_version,
            policy_version=policy_version,
            sources=sources,
            taxonomy_manifest_id=taxonomy_manifest_id or taxonomy_hash,
            acquisition_key=acquisition_key,
            validation_profile_id=report.validation_profile.profile_id,
            validation_profile_digest=report.validation_profile_digest,
            additional_issues=additional_issues,
            sec_integrity_evidence=integrity_evidence,
        )
        source_record = next(
            record
            for record in snapshot.source_records
            if record.source_id == "sec-filing"
        )
        all_facts: list[CanonicalFactV1] = []
        missing_fields: list[str] = list(mapping_missing)
        issues: list[IssueV1] = list(mapping_issues)
        first_selection = FactSelection(None, (), ())
        for index, mapping in enumerate(mappings):
            if mapping.accounting_rules is not None:
                for rule in mapping.accounting_rules.periods:
                    if rule.disposition in {"unknown", "unsupported"}:
                        issues.append(
                            IssueV1(
                                code=f"ACCOUNTING_ROLE_{rule.disposition.upper()}",
                                severity=Severity.ERROR,
                                message=f"{rule.period.period_end.isoformat()}: {rule.rationale}",
                                field=mapping.normalized_field,
                            )
                        )
            candidates = parsed_facts_to_candidates(
                report,
                source=source_record,
                issuer_id=identity.issuer_id,
                security_id=identity.security_id,
                normalized_field=mapping.normalized_field,
                mapping=mapping,
            )
            selection = select_canonical_fact(candidates, valuation_timestamp)
            if index == 0:
                first_selection = selection
            issues.extend(selection.issues)
            grouped = select_fact_groups(candidates, valuation_timestamp)
            issues.extend(issue for item in grouped for issue in item.issues)
            selected = tuple(item.fact for item in grouped if item.fact is not None)
            if not selected:
                missing_fields.append(mapping.normalized_field)
                if not candidates:
                    issues.append(
                        IssueV1(
                            code="FACT_NOT_FOUND",
                            severity=Severity.ERROR,
                            message="no SEC filing fact matched the approved mapping",
                            field=mapping.normalized_field,
                        )
                    )
            quality = (
                QualityStatus.VERIFIED
                if mapping.status == "approved" and mapping.confidence == "high"
                else QualityStatus.PROVISIONAL
            )
            for candidate in selected:
                all_facts.append(
                    candidate.model_copy(
                        update={
                            "quality": quality,
                            "mapping_decision_id": mapping.decision_id,
                            "mapping_confidence": mapping.confidence,
                            "issue_codes": tuple(
                                sorted({issue.code for issue in issues})
                            ),
                        }
                    )
                )
            if mapping.status != "approved" or mapping.confidence != "high":
                issues.append(
                    IssueV1(
                        code="FACT_MAPPING_UNVERIFIED",
                        severity=Severity.WARNING,
                        message="mapping quality does not meet verified coverage",
                        field=mapping.normalized_field,
                    )
                )
        return SecIngestionResult(
            snapshot=snapshot,
            parser_report=report,
            selection=first_selection,
            integrity_evidence=integrity_evidence,
            facts=tuple(all_facts),
            missing_fields=tuple(sorted(set(missing_fields))),
            issues=tuple(issues),
            identity_evidence_ref=identity_evidence_ref,
            mapping_evidence_ref=mapping_evidence_ref,
        )

    def ingest_filing(
        self,
        *,
        identity: IdentityV1,
        cik: str,
        accession_number: str,
        primary_document: str,
        filing_archive_filename: str | None = None,
        filed_at: datetime,
        captured_at: datetime,
        valuation_timestamp: datetime,
        parser_version: str,
        policy_version: str,
        taxonomy_manifest_id: str | None,
        taxonomy_version: str,
        acquisition_key: str | None = None,
        taxonomy_cache_dir: Path,
        normalized_field: str,
        mapping: CanonicalMappingV1,
        dts_filenames: tuple[str, ...] = (),
        profile: ArelleValidationProfileV1 | None = None,
        form: str = "10-K",
        is_amendment: bool = False,
        amends_accession: str | None = None,
        amendment_scope: str | None = None,
        accepted_at: datetime | None = None,
        deadline_at: datetime | None = None,
    ) -> SecIngestionResult:
        if mapping.normalized_field != normalized_field or mapping.status != "approved":
            raise SnapshotError(
                "MAPPING_NOT_APPROVED", "SEC ingestion requires an approved mapping"
            )
        if profile is None:
            raise SnapshotError(
                "VALIDATION_PROFILE_REQUIRED",
                "SEC ingestion requires an explicitly pinned EFM/DQC profile",
            )
        if (
            profile.validation_mode != "sec-efm-dqc"
            or profile.edgar_plugin_dir is None
            or profile.xule_plugin_dir is None
            or profile.dqc_ruleset_path is None
        ):
            raise SnapshotError(
                "SEC_VALIDATION_REQUIRED",
                "SEC ingestion requires the pinned sec-efm-dqc profile",
            )
        index_source = self.source_adapter.capture_filing_index(
            cik=cik,
            accession_number=accession_number,
            filed_at=filed_at,
            captured_at=captured_at,
            deadline_at=deadline_at,
        )
        source = self.source_adapter.capture_filing(
            cik=cik,
            accession_number=accession_number,
            primary_document=primary_document,
            filed_at=filed_at,
            captured_at=captured_at,
            form=form,
            is_amendment=is_amendment,
            amends_accession=amends_accession,
            amendment_scope=amendment_scope,
            accepted_at=accepted_at,
            deadline_at=deadline_at,
        )
        archive_source = self.source_adapter.capture_filing_archive(
            cik=cik,
            accession_number=accession_number,
            filed_at=filed_at,
            filename=filing_archive_filename,
            captured_at=captured_at,
            form=form,
            is_amendment=is_amendment,
            amends_accession=amends_accession,
            amendment_scope=amendment_scope,
            accepted_at=accepted_at,
            deadline_at=deadline_at,
        )
        dts_sources = tuple(
            self.source_adapter.capture_filing_resource(
                cik=cik,
                accession_number=accession_number,
                filename=filename,
                filed_at=filed_at,
                taxonomy_manifest_id=taxonomy_manifest_id,
                is_amendment=is_amendment,
                amends_accession=amends_accession,
                amendment_scope=amendment_scope,
                captured_at=captured_at,
                deadline_at=deadline_at,
            )
            for filename in dts_filenames
        )

        # Keep rejected responses as content-addressed audit evidence before any
        # integrity or parser gate can fail. None are selectable until publish.
        captured_sources = tuple(
            SecCapturedSourceEvidenceV1(
                source_id=item.source_id,
                uri=item.uri,
                role=item.role,
                media_type=item.media_type,
                http_status=item.http_status,
                available_at=item.available_at,
                captured_at=item.captured_at or item.available_at,
                publication_at=item.publication_at,
                accession_number=item.accession_number,
                form=item.form,
                filed_at=item.filed_at,
                response_headers=item.response_headers,
                declared_size=item.declared_size,
                received_size=(
                    item.received_size
                    if item.received_size is not None
                    else len(item.content)
                ),
                content_hash=self.content_store.put(
                    item.content, media_type=item.media_type
                ),
            )
            for item in (index_source, source, archive_source, *dts_sources)
        )
        assessment = assess_filing_response(
            raw_response=source,
            archive_index=index_source,
            archive=archive_source,
        )
        normalized_hash = self.content_store.put(
            assessment.normalized_content, media_type=source.media_type
        )
        archive_member_hash = self.content_store.put(
            assessment.archive_member, media_type=source.media_type
        )
        if normalized_hash != assessment.normalized_content_hash:
            raise SnapshotError(
                "SOURCE_HASH_MISMATCH", "normalized SEC artifact failed hash check"
            )

        with tempfile.TemporaryDirectory(prefix="fundamental-sec-filing-") as directory:
            root = Path(directory)
            normalized_root = root / "normalized"
            archive_root = root / "archive"
            normalized_root.mkdir()
            archive_root.mkdir()
            normalized_path = normalized_root / primary_document
            archive_member_path = archive_root / primary_document
            normalized_path.write_bytes(assessment.normalized_content)
            archive_member_path.write_bytes(assessment.archive_member)
            _stage_filing_graphics(
                (normalized_root, archive_root),
                html_content=assessment.normalized_content,
                archive_content=archive_source.content,
                primary_document=primary_document,
            )
            for resource in dts_sources:
                filename = Path(resource.uri).name
                (normalized_root / filename).write_bytes(resource.content)
                (archive_root / filename).write_bytes(resource.content)
            parser_report = parse_filing_offline(
                normalized_path,
                profile=profile,
                taxonomy_version=taxonomy_version,
                taxonomy_cache_dir=taxonomy_cache_dir,
                source_content_hash=normalized_hash,
            )
            require_sec_validation_evidence(parser_report)
            archive_report = parser_report
            if assessment.relation == "normalized":
                archive_report = parse_filing_offline(
                    archive_member_path,
                    profile=profile,
                    taxonomy_version=taxonomy_version,
                    taxonomy_cache_dir=taxonomy_cache_dir,
                    source_content_hash=archive_member_hash,
                )
                require_sec_validation_evidence(archive_report)
                if fact_semantic_digest(parser_report) != fact_semantic_digest(
                    archive_report
                ) or self._finding_signature(parser_report) != self._finding_signature(
                    archive_report
                ):
                    raise SnapshotError(
                        "NORMALIZATION_SEMANTIC_MISMATCH",
                        "normalized and SEC archive XBRL semantics differ",
                    )

        fact_digest = fact_semantic_digest(parser_report)
        archive_fact_digest = fact_semantic_digest(archive_report)
        blocking_codes = set(parser_report.blocking_finding_codes())
        finding_evidence = tuple(
            ArelleFindingEvidenceV1.model_validate(
                {
                    "code": item.code,
                    "severity": item.severity,
                    "blocks": item.code in blocking_codes,
                    "rule_severity": item.rule_severity,
                }
            )
            for item in parser_report.findings
        )
        taxonomy_hash = parser_report.taxonomy_cache_hash
        if taxonomy_hash is None:
            raise SnapshotError(
                "TAXONOMY_MANIFEST_MISSING",
                "offline parser did not produce a taxonomy manifest hash",
            )

        integrity_evidence = SecIntegrityEvidenceV1(
            accession_number=accession_number,
            primary_document_uri=source.uri,
            captured_at=source.captured_at or captured_at,
            archive_index_uri=index_source.uri,
            archive_index_hash=assessment.archive_index_hash,
            declared_primary_size=assessment.declared_primary_size,
            raw_response_headers=source.response_headers,
            raw_received_size=source.received_size or len(source.content),
            raw_content_hash=assessment.raw_content_hash,
            declared_response_size=source.declared_size,
            archive_uri=archive_source.uri,
            archive_size=archive_source.received_size or len(archive_source.content),
            archive_hash=assessment.archive_hash,
            archive_member_name=assessment.archive_member_name,
            archive_member_size=len(assessment.archive_member),
            archive_member_hash=assessment.archive_member_hash,
            integrity_relation=assessment.relation,
            normalized_content_size=len(assessment.normalized_content),
            normalized_content_hash=normalized_hash,
            normalization_policy_id=assessment.normalization_policy_id,
            normalization_rule_signature=assessment.normalization_rule_signature,
            normalization_reason=assessment.normalization_reason,
            removed_ranges=assessment.removed_ranges,
            normalized_fact_count=len(parser_report.facts),
            normalized_fact_digest=fact_digest,
            archive_fact_count=len(archive_report.facts),
            archive_fact_digest=archive_fact_digest,
            parser_input_hash=parser_report.source_content_hash or "",
            validation_profile_digest=parser_report.validation_profile_digest,
            validation_engines=parser_report.validation_engines,
            validation_evidence=parser_report.validation_evidence,
            network_attempt_count=parser_report.network_attempt_count,
            taxonomy_manifest_hash=taxonomy_hash,
            arelle_version=profile.arelle_version,
            efm_profile=profile.efm_profile,
            dqc_version=profile.dqc_version,
            xule_version=profile.xule_version,
            findings=finding_evidence,
            quality_decision="block" if blocking_codes else "pass",
        )

        if blocking_codes:
            rejection_evidence = SecIngestionRejectionEvidenceV1(
                contract_version="fundamental.sec-ingestion-rejection.v1",
                error_code="PARSER_VALIDATION_BLOCKED",
                captured_sources=captured_sources,
                integrity_evidence=integrity_evidence,
                parser_replay_digests=tuple(
                    sorted(
                        {parser_report.replay_digest(), archive_report.replay_digest()}
                    )
                ),
            )
            evidence_digest = sha256_digest(rejection_evidence)
            accession_id = "".join(
                character
                for character in accession_number
                if character.isascii() and character.isalnum()
            )
            artifact_id = f"sec-ingestion-rejection-{accession_id}-{evidence_digest}"
            dependency_hashes = tuple(
                sorted(
                    {
                        *(item.content_hash for item in captured_sources),
                        assessment.normalized_content_hash,
                        assessment.archive_member_hash,
                        parser_report.validation_profile_digest,
                        taxonomy_hash,
                    }
                )
            )
            record = self.audit_store.put(
                artifact_id,
                rejection_evidence,
                dependency_hashes,
                retention="evidence",
            )
            raise SnapshotError(
                "PARSER_VALIDATION_BLOCKED",
                "blocking SEC EFM/DQC findings prevent canonical fact publication",
                evidence_ref=record.artifact_id,
            )
        if not parser_report.facts:
            raise SnapshotError("PARSER_FACTS_MISSING", "Arelle produced no XBRL facts")

        all_sources = (index_source, source, archive_source, *dts_sources)
        prepared = self.builder.prepare(
            identity=identity,
            valuation_timestamp=valuation_timestamp,
            captured_at=max(
                captured_at,
                *(item.captured_at or captured_at for item in all_sources),
            ),
            parser_version=parser_version,
            policy_version=policy_version,
            sources=all_sources,
            taxonomy_manifest_id=taxonomy_manifest_id or taxonomy_hash,
            acquisition_key=acquisition_key,
            validation_profile_id=profile.profile_id,
            validation_profile_digest=parser_report.validation_profile_digest,
            sec_integrity_evidence=integrity_evidence,
        )
        source_record = next(
            record
            for record in prepared.source_records
            if record.source_id == "sec-filing"
        )
        candidates = parsed_facts_to_candidates(
            parser_report,
            source=source_record,
            issuer_id=identity.issuer_id,
            normalized_field=normalized_field,
            mapping=mapping,
        )
        selection = select_canonical_fact(candidates, valuation_timestamp)
        if selection.fact is None:
            raise SnapshotError(
                "POINT_IN_TIME_FACT_UNAVAILABLE",
                "approved mapping has no eligible fact at the valuation timestamp",
            )
        if selection.fact.quality.value != "verified":
            raise SnapshotError(
                "CANONICAL_FACT_NOT_VERIFIED",
                "selected SEC canonical fact did not pass quality gates",
            )

        self.builder.publish(prepared)
        if self.fact_repository is not None:
            self.fact_repository.publish(selection.fact)
        return SecIngestionResult(
            snapshot=prepared,
            parser_report=parser_report,
            selection=selection,
            integrity_evidence=integrity_evidence,
        )

    @staticmethod
    def _finding_signature(
        report: ArelleParseReportV1,
    ) -> tuple[tuple[str, str, bool], ...]:
        blocking = set(report.blocking_finding_codes())
        return tuple(
            sorted(
                (item.code, item.severity, item.code in blocking)
                for item in report.findings
            )
        )
