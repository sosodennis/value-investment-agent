import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile

import pytest
from fundamental_service.arelle_parser import (
    ArelleParseReportV1,
    ArelleValidationProfileV1,
    ParsedXbrlFactV1,
    parse_filing_offline,
)
from fundamental_service.contracts import IdentityV1, SourceRecordV1, SourceRole
from fundamental_service.facts import CanonicalMappingV1
from fundamental_service.sec_rebuild import (
    parsed_facts_to_candidates,
    select_canonical_fact,
)
from fundamental_service.sec_source import sec_source_register
from fundamental_service.snapshots import (
    CapturedSource,
    FilesystemContentStore,
    FilesystemSnapshotRepository,
    SnapshotBuilder,
    SnapshotError,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "sec-edgar"
UTC = timezone.utc


def _rebuild_source(content_hash: str) -> SourceRecordV1:
    return SourceRecordV1(
        source_id="sec-filing",
        uri="https://www.sec.gov/Archives/edgar/data/320193/filing.htm",
        role=SourceRole.FILING,
        available_at=datetime(2024, 11, 1, tzinfo=UTC),
        captured_at=datetime(2026, 1, 1, tzinfo=UTC),
        publication_at=datetime(2024, 11, 1, tzinfo=UTC),
        http_status=200,
        media_type="text/html",
        terms_reference="https://www.sec.gov/submit-filings/about-edgar-filer-access",
        content_hash=content_hash,
        parser_version="2.47.4",
        accession_number="0000320193-24-000123",
        form="10-K",
        filed_at=datetime(2024, 11, 1, tzinfo=UTC),
        filing_version="0000320193-24-000123",
    )


def _rebuild_report(content_hash: str, **kwargs: object) -> ArelleParseReportV1:
    return ArelleParseReportV1(
        filing_path="/tmp/filing.htm",
        parser_version="2.47.4",
        taxonomy_version="us-gaap-2024",
        validation_profile=ArelleValidationProfileV1(profile_id="sec-efm-us-gaap-v1"),
        parsed_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_content_hash=content_hash,
        **kwargs,
    )


def test_blocking_parser_finding_prevents_fact_rebuild():
    source = _rebuild_source("a" * 64)
    report = _rebuild_report("a" * 64, finding_codes=("IOerror",))
    with pytest.raises(SnapshotError) as error:
        parsed_facts_to_candidates(
            report,
            source=source,
            issuer_id="0000320193",
            normalized_field="revenue",
        )
    assert error.value.code == "PARSER_VALIDATION_BLOCKED"


def test_issuer_mismatch_prevents_fact_rebuild():
    source = _rebuild_source("b" * 64)
    report = _rebuild_report(
        "b" * 64,
        facts=(
            ParsedXbrlFactV1(
                concept="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                value="100",
                context_id="ctx-1",
                unit="iso4217:USD",
                entity_identifier="0000999999",
                period_start=datetime(2024, 1, 1).date(),
                period_end=datetime(2024, 12, 31).date(),
                is_numeric=True,
            ),
        ),
    )
    with pytest.raises(SnapshotError) as error:
        parsed_facts_to_candidates(
            report,
            source=source,
            issuer_id="0000320193",
            normalized_field="revenue",
        )
    assert error.value.code == "ISSUER_MISMATCH"


def test_selection_filters_unavailable_newer_period_before_selecting_latest():
    source = _rebuild_source("c" * 64).model_copy(
        update={"available_at": datetime(2023, 11, 1, tzinfo=UTC)}
    )
    report = _rebuild_report(
        "c" * 64,
        facts=(
            ParsedXbrlFactV1(
                concept="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                value="100",
                context_id="ctx-old",
                unit="iso4217:USD",
                entity_identifier="0000320193",
                period_start=datetime(2023, 1, 1).date(),
                period_end=datetime(2023, 12, 31).date(),
                is_numeric=True,
                consolidation_scope="consolidated",
            ),
        ),
    )
    candidates = parsed_facts_to_candidates(
        report,
        source=source,
        issuer_id="0000320193",
        normalized_field="revenue",
    )
    newer = candidates[0].model_copy(
        update={
            "candidate_id": "sec-fact-newer",
            "value": Decimal("200"),
            "period_start": datetime(2024, 1, 1).date(),
            "period_end": datetime(2024, 12, 31).date(),
            "as_of": datetime(2024, 12, 31, tzinfo=UTC),
            "available_at": datetime(2025, 1, 2, tzinfo=UTC),
        }
    )
    selection = select_canonical_fact(
        (candidates[0], newer), datetime(2024, 1, 1, tzinfo=UTC)
    )
    assert selection.fact is not None
    assert selection.fact.value == Decimal("100")


def test_selection_prefers_annual_period_over_quarterly_period_in_one_filing():
    source = _rebuild_source("d" * 64).model_copy(
        update={"available_at": datetime(2024, 1, 1, tzinfo=UTC)}
    )
    report = _rebuild_report(
        "d" * 64,
        facts=(
            ParsedXbrlFactV1(
                concept="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                value="100",
                context_id="ctx-annual",
                unit="iso4217:USD",
                entity_identifier="0000320193",
                period_start=datetime(2023, 1, 1).date(),
                period_end=datetime(2023, 12, 31).date(),
                is_numeric=True,
                consolidation_scope="consolidated",
            ),
            ParsedXbrlFactV1(
                concept="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                value="25",
                context_id="ctx-quarter",
                unit="iso4217:USD",
                entity_identifier="0000320193",
                period_start=datetime(2023, 10, 1).date(),
                period_end=datetime(2023, 12, 31).date(),
                is_numeric=True,
                consolidation_scope="consolidated",
            ),
        ),
    )
    candidates = parsed_facts_to_candidates(
        report,
        source=source,
        issuer_id="0000320193",
        normalized_field="revenue",
    )
    selection = select_canonical_fact(candidates, datetime(2024, 2, 1, tzinfo=UTC))
    assert selection.fact is not None
    assert selection.fact.period_start == datetime(2023, 1, 1).date()
    assert selection.fact.period_end == datetime(2023, 12, 31).date()


def test_selection_uses_latest_available_filing_over_newer_economic_period():
    source = _rebuild_source("e" * 64)
    report = _rebuild_report(
        "e" * 64,
        facts=(
            ParsedXbrlFactV1(
                concept="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                value="100",
                context_id="ctx-base",
                unit="iso4217:USD",
                entity_identifier="0000320193",
                period_start=datetime(2023, 1, 1).date(),
                period_end=datetime(2023, 12, 31).date(),
                is_numeric=True,
                consolidation_scope="consolidated",
            ),
        ),
    )
    base = parsed_facts_to_candidates(
        report,
        source=source,
        issuer_id="0000320193",
        normalized_field="revenue",
    )[0]
    later_available = base.model_copy(
        update={
            "candidate_id": "sec-fact-later-available",
            "value": Decimal("90"),
            "period_start": datetime(2022, 1, 1).date(),
            "period_end": datetime(2022, 12, 31).date(),
            "as_of": datetime(2022, 12, 31, tzinfo=UTC),
            "available_at": datetime(2024, 2, 1, tzinfo=UTC),
        }
    )
    newer_period = base.model_copy(
        update={
            "candidate_id": "sec-fact-newer-period",
            "value": Decimal("110"),
            "period_start": datetime(2024, 1, 1).date(),
            "period_end": datetime(2024, 12, 31).date(),
            "as_of": datetime(2024, 12, 31, tzinfo=UTC),
            "available_at": datetime(2024, 1, 1, tzinfo=UTC),
            "source": base.source.model_copy(
                update={
                    "content_hash": "f" * 64,
                    "accession_number": "0000320193-24-000124",
                }
            ),
            "accession_number": "0000320193-24-000124",
            "filing_version": "0000320193-24-000124",
        }
    )
    selection = select_canonical_fact(
        (later_available, newer_period), datetime(2025, 1, 1, tzinfo=UTC)
    )
    assert selection.fact is not None
    assert selection.fact.fact_id == "sec-fact-later-available"


def test_captured_sec_bytes_rebuild_to_point_in_time_canonical_fact(tmp_path: Path):
    manifest = json.loads((FIXTURE_ROOT / "capture_manifest.json").read_text())
    sources = {record["path"]: record for record in manifest["sources"]}
    filing_record = sources["apple-2024-original-aapl-20240928.htm"]
    taxonomy_record = sources["apple-2024-original-0000320193-24-000123-xbrl.zip"]
    captured_sources = tuple(
        CapturedSource(
            source_id=record["source_id"],
            uri=record["uri"],
            role=SourceRole(record["role"]),
            content=(FIXTURE_ROOT / path).read_bytes(),
            media_type=record["media_type"],
            http_status=record["http_status"],
            available_at=datetime.fromisoformat(record["available_at"]),
            publication_at=datetime.fromisoformat(record["publication_at"]),
            accession_number=record["accession_number"],
            form=record["form"],
            filed_at=(
                datetime.fromisoformat(record["filed_at"])
                if record["filed_at"]
                else None
            ),
            filing_version=record["filing_version"],
            is_amendment=record["is_amendment"],
            amends_accession=record["amends_accession"],
            amendment_scope=record["amendment_scope"],
        )
        for path, record in (
            ("apple-2024-original-aapl-20240928.htm", filing_record),
            (
                "apple-2024-original-0000320193-24-000123-xbrl.zip",
                taxonomy_record,
            ),
        )
    )
    repository = FilesystemSnapshotRepository(tmp_path / "snapshots")
    snapshot = SnapshotBuilder(
        FilesystemContentStore(tmp_path / "objects"),
        repository,
        sec_source_register(),
    ).build(
        identity=IdentityV1(
            issuer_id="0000320193",
            issuer_name="Apple Inc.",
            domicile="US",
            reporting_basis="us-gaap",
            security_id="AAPL",
            share_class="common",
            currency="USD",
        ),
        valuation_timestamp=datetime(2025, 1, 1, tzinfo=UTC),
        captured_at=datetime(2026, 11, 3, tzinfo=UTC),
        parser_version="arelle-release==2.47.4",
        policy_version="source-policy-v1",
        sources=captured_sources,
        taxonomy_manifest_id=hashlib.sha256(
            (
                FIXTURE_ROOT / "apple-2024-original-0000320193-24-000123-xbrl.zip"
            ).read_bytes()
        ).hexdigest(),
    )
    assert snapshot.coverage_status.value == "verified"
    assert repository.get(snapshot.snapshot_id).snapshot_id == snapshot.snapshot_id

    filing_dir = tmp_path / "filing"
    filing_dir.mkdir()
    (filing_dir / "aapl-20240928.htm").write_bytes(
        (FIXTURE_ROOT / "apple-2024-original-aapl-20240928.htm").read_bytes()
    )
    with ZipFile(
        FIXTURE_ROOT / "apple-2024-original-0000320193-24-000123-xbrl.zip"
    ) as archive:
        for filename in (
            "aapl-20240928.xsd",
            "aapl-20240928_pre.xml",
            "aapl-20240928_def.xml",
            "aapl-20240928_lab.xml",
            "aapl-20240928_cal.xml",
        ):
            (filing_dir / filename).write_bytes(archive.read(filename))
    taxonomy_dir = tmp_path / "taxonomy"
    with ZipFile(FIXTURE_ROOT / "arelle-taxonomy-cache-2024.zip") as archive:
        archive.extractall(taxonomy_dir)
    report = parse_filing_offline(
        filing_dir / "aapl-20240928.htm",
        profile=ArelleValidationProfileV1(profile_id="sec-efm-us-gaap-v1"),
        taxonomy_version="us-gaap-2024",
        taxonomy_cache_dir=taxonomy_dir,
        source_content_hash=filing_record["sha256"],
    )
    source_record = next(
        record
        for record in snapshot.source_records
        if record.uri == filing_record["uri"]
    )
    candidates = parsed_facts_to_candidates(
        report,
        source=source_record,
        issuer_id="0000320193",
        normalized_field="revenue",
        mapping=CanonicalMappingV1(
            contract_version="fundamental.v1",
            decision_id="map-us-gaap-revenue-v1",
            source_concept="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            normalized_field="revenue",
            mapping_version="sec-us-gaap-v1",
            confidence="high",
            evidence_refs=(filing_record["sha256"],),
            reviewer="fundamental-service",
            reviewed_at=datetime(2025, 1, 1, tzinfo=UTC),
            status="approved",
        ),
    )
    revenue = tuple(
        candidate
        for candidate in candidates
        if candidate.concept
        == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
        and candidate.period_end is not None
        and candidate.period_end.isoformat() == "2024-09-28"
        and not candidate.dimensions
    )
    selection = select_canonical_fact(revenue, datetime(2025, 1, 1, tzinfo=UTC))
    assert selection.fact is not None
    assert selection.fact.value == 391035000000
    assert selection.fact.source.content_hash == filing_record["sha256"]
    assert selection.fact.context.context_id
    assert selection.fact.available_at <= datetime(2025, 1, 1, tzinfo=UTC)
