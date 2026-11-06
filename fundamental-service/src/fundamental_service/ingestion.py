"""Service-owned SEC acquisition, offline validation, and gated publication."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from .arelle_parser import (
    ArelleParseReportV1,
    ArelleValidationProfileV1,
    fact_semantic_digest,
    parse_filing_offline,
)
from .contracts import (
    ArelleFindingEvidenceV1,
    IdentityV1,
    SecCapturedSourceEvidenceV1,
    SecIngestionRejectionEvidenceV1,
    SecIntegrityEvidenceV1,
)
from .facts import CanonicalFactRepository, CanonicalMappingV1, FactSelection
from .replay import ArtifactRecordV1
from .sec_integrity import assess_filing_response, extract_referenced_graphics
from .sec_rebuild import parsed_facts_to_candidates, select_canonical_fact
from .sec_source import SecEdgarSourceAdapter, sec_source_register
from .serialization import sha256_digest
from .snapshots import (
    ContentAddressedStore,
    SnapshotBuilder,
    SnapshotError,
    SnapshotRepository,
    SourceSnapshotV1,
)


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
class SecIngestionResult:
    snapshot: SourceSnapshotV1
    parser_report: ArelleParseReportV1
    selection: FactSelection
    integrity_evidence: SecIntegrityEvidenceV1


class SecIngestionService:
    """Own SEC I/O, byte integrity, parser gates, and snapshot publication."""

    def __init__(
        self,
        *,
        source_adapter: SecEdgarSourceAdapter,
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
            content_store,
            snapshot_repository,
            sec_source_register(),
        )

    def ingest_filing(
        self,
        *,
        identity: IdentityV1,
        cik: str,
        accession_number: str,
        primary_document: str,
        filed_at: datetime,
        captured_at: datetime,
        valuation_timestamp: datetime,
        parser_version: str,
        policy_version: str,
        taxonomy_manifest_id: str | None,
        taxonomy_version: str,
        taxonomy_cache_dir: Path,
        normalized_field: str,
        mapping: CanonicalMappingV1,
        dts_filenames: tuple[str, ...] = (),
        profile: ArelleValidationProfileV1 | None = None,
        form: str = "10-K",
        is_amendment: bool = False,
        amends_accession: str | None = None,
        amendment_scope: str | None = None,
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
        )
        source = self.source_adapter.capture_filing(
            cik=cik,
            accession_number=accession_number,
            primary_document=primary_document,
            filed_at=filed_at,
            form=form,
            is_amendment=is_amendment,
            amends_accession=amends_accession,
            amendment_scope=amendment_scope,
        )
        archive_source = self.source_adapter.capture_filing_archive(
            cik=cik,
            accession_number=accession_number,
            filed_at=filed_at,
            form=form,
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
            graphics = extract_referenced_graphics(
                html_content=assessment.normalized_content,
                archive_content=archive_source.content,
                primary_document=primary_document,
            )
            for relative_path, content in graphics:
                normalized_resource = normalized_root / relative_path
                archive_resource = archive_root / relative_path
                normalized_resource.parent.mkdir(parents=True, exist_ok=True)
                archive_resource.parent.mkdir(parents=True, exist_ok=True)
                normalized_resource.write_bytes(content)
                archive_resource.write_bytes(content)
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
            self._require_validation_evidence(parser_report)
            archive_report = parser_report
            if assessment.relation == "normalized":
                archive_report = parse_filing_offline(
                    archive_member_path,
                    profile=profile,
                    taxonomy_version=taxonomy_version,
                    taxonomy_cache_dir=taxonomy_cache_dir,
                    source_content_hash=archive_member_hash,
                )
                self._require_validation_evidence(archive_report)
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
            ArelleFindingEvidenceV1(
                code=item.code,
                severity=item.severity,
                blocks=item.code in blocking_codes,
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
            declared_primary_size=int(assessment.archive_index_entry["size"]),
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

    @staticmethod
    def _require_validation_evidence(report: ArelleParseReportV1) -> None:
        if report.validation_profile.validation_mode != "sec-efm-dqc":
            raise SnapshotError(
                "SEC_VALIDATION_REQUIRED",
                "SEC parser report was not produced by sec-efm-dqc",
            )
        if not {"sec-efm", "dqc-us"}.issubset(report.validation_engines):
            raise SnapshotError(
                "VALIDATION_EVIDENCE_MISSING",
                "SEC parser report lacks EFM/DQC engine evidence",
            )
        if not {
            "strict-sec-efm-profile-selected",
            "dqc-dqcrt-checks-completed",
        }.issubset(report.validation_evidence):
            raise SnapshotError(
                "VALIDATION_EVIDENCE_MISSING",
                "SEC parser report lacks EFM/DQC completion evidence",
            )
        if report.network_attempt_count != 0:
            raise SnapshotError(
                "OFFLINE_NETWORK_ATTEMPT",
                "SEC parser report records a network attempt",
            )
