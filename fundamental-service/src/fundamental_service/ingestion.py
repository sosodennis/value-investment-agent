"""Service-owned source ingestion and offline SEC fact rebuild orchestration."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .arelle_parser import (
    ArelleParseReportV1,
    ArelleValidationProfileV1,
    parse_filing_offline,
)
from .contracts import CanonicalFactV1, IdentityV1, IssueV1, QualityStatus
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
    SnapshotRepository,
    SourceSnapshotV1,
)


@dataclass(frozen=True)
class SecIngestionResult:
    snapshot: SourceSnapshotV1
    parser_report: ArelleParseReportV1
    selection: FactSelection
    facts: tuple[CanonicalFactV1, ...] = ()
    missing_fields: tuple[str, ...] = ()
    issues: tuple[IssueV1, ...] = ()


class SecIngestionService:
    """Keep provider I/O, immutable persistence, parsing, and fact selection in one boundary."""

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
        source = self.source_adapter.capture_filing(
            cik=cik,
            accession_number=accession_number,
            primary_document=primary_document,
            filed_at=filed_at,
            accepted_at=accepted_at,
            form=form,
            is_amendment=is_amendment,
            amends_accession=amends_accession,
            amendment_scope=amendment_scope,
            deadline_at=deadline_at,
        )
        dts_sources = tuple(
            self.source_adapter.capture_filing_resource(
                cik=cik,
                accession_number=accession_number,
                filename=filename,
                filed_at=accepted_at or filed_at,
                taxonomy_manifest_id=taxonomy_manifest_id,
                is_amendment=is_amendment,
                amends_accession=amends_accession,
                amendment_scope=amendment_scope,
                deadline_at=deadline_at,
            )
            for filename in dts_filenames
        )
        sources = (*reference_sources, source, *dts_sources)
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
            if record.role.value == "filing"
        )
        profile = profile or ArelleValidationProfileV1(profile_id="sec-efm-us-gaap-v1")
        with tempfile.TemporaryDirectory(prefix="fundamental-sec-filing-") as directory:
            filing_path = Path(directory) / primary_document
            filing_path.write_bytes(source.content)
            for resource in dts_sources:
                (Path(directory) / Path(resource.uri).name).write_bytes(
                    resource.content
                )
            report = parse_filing_offline(
                filing_path,
                profile=profile,
                taxonomy_version=taxonomy_version,
                taxonomy_cache_dir=taxonomy_cache_dir,
                source_content_hash=source_record.content_hash,
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
