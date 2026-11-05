"""Service-owned source ingestion and offline SEC fact rebuild orchestration."""

from __future__ import annotations

import tempfile
import zlib
from dataclasses import dataclass, replace
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from .arelle_parser import (
    ArelleParseReportV1,
    ArelleValidationProfileV1,
    parse_filing_offline,
)
from .contracts import (
    CanonicalFactV1,
    IdentityV1,
    IssueV1,
    QualityStatus,
    SourceRole,
)
from .facts import (
    CanonicalFactRepository,
    CanonicalMappingV1,
    FactSelection,
    select_fact_groups,
)
from .sec_rebuild import parsed_facts_to_candidates, select_canonical_fact
from .sec_source import SecEdgarSourceAdapter, sec_source_register
from .snapshots import (
    CapturedSource,
    ContentAddressedStore,
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


@dataclass(frozen=True)
class SecIngestionResult:
    snapshot: SourceSnapshotV1
    parser_report: ArelleParseReportV1
    selection: FactSelection
    facts: tuple[CanonicalFactV1, ...] = ()
    missing_fields: tuple[str, ...] = ()
    issues: tuple[IssueV1, ...] = ()


class SecIngestionService:
    """Keep source I/O, immutable persistence, and fact selection in one boundary."""

    def __init__(
        self,
        *,
        source_adapter: SecEdgarSourceAdapter,
        content_store: ContentAddressedStore,
        snapshot_repository: SnapshotRepository,
        fact_repository: CanonicalFactRepository | None = None,
    ) -> None:
        self.source_adapter = source_adapter
        self.fact_repository = fact_repository
        self.builder = SnapshotBuilder(
            content_store, snapshot_repository, sec_source_register()
        )

    def prepare_filing(
        self,
        *,
        identity: IdentityV1,
        cik: str,
        accession_number: str,
        primary_document: str,
        filing_archive_filename: str,
        filed_at: datetime,
        captured_at: datetime,
        valuation_timestamp: datetime,
        parser_version: str,
        policy_version: str,
        taxonomy_manifest_id: str | None,
        taxonomy_version: str,
        taxonomy_cache_dir: Path,
        mappings: tuple[CanonicalMappingV1, ...],
        reference_sources: tuple[CapturedSource, ...] = (),
        accepted_at: datetime | None = None,
        deadline_at: datetime | None = None,
        dts_filenames: tuple[str, ...] = (),
        profile: ArelleValidationProfileV1 | None = None,
        form: str = "10-K",
        is_amendment: bool = False,
        amends_accession: str | None = None,
        amendment_scope: str | None = None,
    ) -> SecIngestionResult:
        archive_source = self.source_adapter.capture_filing_archive(
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
        members = _read_sec_xbrl_archive(
            archive_source.content,
            primary_document=primary_document,
            dts_filenames=dts_filenames,
        )
        source = replace(
            archive_source,
            source_id="sec-filing",
            uri=f"{archive_source.uri}#member={primary_document}",
            content=members[primary_document],
            media_type="text/html",
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
        sources = (*reference_sources, archive_source, source, *dts_sources)
        profile = profile or ArelleValidationProfileV1(profile_id="sec-efm-us-gaap-v1")
        snapshot = self.builder.prepare(
            identity=identity,
            valuation_timestamp=valuation_timestamp,
            captured_at=captured_at,
            parser_version=parser_version,
            policy_version=policy_version,
            sources=sources,
            taxonomy_manifest_id=taxonomy_manifest_id,
        )
        source_record = next(
            record
            for record in snapshot.source_records
            if record.source_id == "sec-filing"
        )
        with tempfile.TemporaryDirectory(prefix="fundamental-sec-filing-") as directory:
            filing_path = Path(directory) / primary_document
            filing_path.write_bytes(source.content)
            for filename in dts_filenames:
                (Path(directory) / filename).write_bytes(members[filename])
            report = parse_filing_offline(
                filing_path,
                profile=profile,
                taxonomy_version=taxonomy_version,
                taxonomy_cache_dir=taxonomy_cache_dir,
                source_content_hash=source_record.content_hash,
                deadline_at=deadline_at,
            )
        snapshot = self.builder.prepare(
            identity=identity,
            valuation_timestamp=valuation_timestamp,
            captured_at=captured_at,
            parser_version=parser_version,
            policy_version=policy_version,
            sources=sources,
            taxonomy_manifest_id=taxonomy_manifest_id,
            validation_profile_id=report.validation_profile.profile_id,
            validation_profile_digest=report.validation_profile_digest,
        )
        all_facts: list[CanonicalFactV1] = []
        missing_fields: list[str] = []
        issues: list[IssueV1] = []
        first_selection = FactSelection(None, (), ())
        for index, mapping in enumerate(mappings):
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
                            severity="error",
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
                        severity="warning",
                        message="mapping quality does not meet verified coverage",
                        field=mapping.normalized_field,
                    )
                )
        return SecIngestionResult(
            snapshot=snapshot,
            parser_report=report,
            selection=first_selection,
            facts=tuple(all_facts),
            missing_fields=tuple(sorted(set(missing_fields))),
            issues=tuple(issues),
        )

    def ingest_filing(
        self,
        *,
        identity: IdentityV1,
        cik: str,
        accession_number: str,
        primary_document: str,
        filing_archive_filename: str,
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
        if mapping.normalized_field != normalized_field:
            raise ValueError("mapping does not target normalized_field")
        return self.prepare_filing(
            identity=identity,
            cik=cik,
            accession_number=accession_number,
            primary_document=primary_document,
            filing_archive_filename=filing_archive_filename,
            filed_at=filed_at,
            captured_at=captured_at,
            valuation_timestamp=valuation_timestamp,
            parser_version=parser_version,
            policy_version=policy_version,
            taxonomy_manifest_id=taxonomy_manifest_id,
            taxonomy_version=taxonomy_version,
            taxonomy_cache_dir=taxonomy_cache_dir,
            mappings=(mapping,),
            dts_filenames=dts_filenames,
            profile=profile,
            form=form,
            is_amendment=is_amendment,
            amends_accession=amends_accession,
            amendment_scope=amendment_scope,
        )
