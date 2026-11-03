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
from .contracts import IdentityV1
from .facts import CanonicalMappingV1, FactSelection
from .sec_rebuild import parsed_facts_to_candidates, select_canonical_fact
from .sec_source import SecEdgarSourceAdapter, sec_source_register
from .snapshots import (
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


class SecIngestionService:
    """Keep provider I/O, immutable persistence, parsing, and fact selection in one boundary.

    Calculation code never uses this service. It receives the returned snapshot
    ID and canonical facts after this bounded ingestion call completes.
    """

    def __init__(
        self,
        *,
        source_adapter: SecEdgarSourceAdapter,
        content_store: ContentAddressedStore,
        snapshot_repository: SnapshotRepository,
    ) -> None:
        self.source_adapter = source_adapter
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
        snapshot = self.builder.build(
            identity=identity,
            valuation_timestamp=valuation_timestamp,
            captured_at=captured_at,
            parser_version=parser_version,
            policy_version=policy_version,
            sources=(source, *dts_sources),
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
        candidates = parsed_facts_to_candidates(
            report,
            source=source_record,
            issuer_id=identity.issuer_id,
            normalized_field=normalized_field,
            mapping=mapping,
        )
        selection = select_canonical_fact(candidates, valuation_timestamp)
        return SecIngestionResult(
            snapshot=snapshot, parser_report=report, selection=selection
        )
