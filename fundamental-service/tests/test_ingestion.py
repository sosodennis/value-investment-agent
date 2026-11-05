import hashlib
from datetime import datetime, timezone
from email.message import Message
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from fundamental_service.contracts import IdentityV1
from fundamental_service.facts import CanonicalMappingV1
from fundamental_service.ingestion import SecIngestionService, _read_sec_xbrl_archive
from fundamental_service.sec_source import SecEdgarSourceAdapter, SecRequestPolicy
from fundamental_service.snapshots import (
    FilesystemContentStore,
    FilesystemSnapshotRepository,
    SnapshotError,
)


class Response:
    status = 200

    def __init__(self, payload: bytes):
        self.payload = payload
        self.headers = Message()
        self.headers["Content-Type"] = "application/zip"

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_sec_xbrl_archive_rejects_missing_or_duplicate_required_members():
    archive_buffer = BytesIO()
    with ZipFile(archive_buffer, "w") as archive:
        archive.writestr("../aapl-20240928.htm", b"unsafe path")
        archive.writestr("aapl-20240928.xsd", b"<schema/>")

    with pytest.raises(SnapshotError, match="missing an index-selected member"):
        _read_sec_xbrl_archive(
            archive_buffer.getvalue(),
            primary_document="aapl-20240928.htm",
            dts_filenames=("aapl-20240928.xsd",),
        )

    duplicate_buffer = BytesIO()
    with pytest.warns(UserWarning, match="Duplicate name"):
        with ZipFile(duplicate_buffer, "w") as archive:
            archive.writestr("aapl-20240928.htm", b"canonical")
            archive.writestr("aapl-20240928.htm", b"challenge-polluted")
            archive.writestr("aapl-20240928.xsd", b"<schema/>")
    with pytest.raises(SnapshotError, match="repeats a member name"):
        _read_sec_xbrl_archive(
            duplicate_buffer.getvalue(),
            primary_document="aapl-20240928.htm",
            dts_filenames=("aapl-20240928.xsd",),
        )


def test_sec_ingestion_connects_adapter_snapshot_parser_and_fact_selection(
    tmp_path: Path,
):
    fixture_root = Path(__file__).parent / "fixtures" / "sec-edgar"
    direct_filing_bytes = (
        fixture_root / "apple-2024-original-aapl-20240928.htm"
    ).read_bytes()
    archive_bytes = (
        fixture_root / "apple-2024-original-0000320193-24-000123-xbrl.zip"
    ).read_bytes()
    with ZipFile(
        fixture_root / "apple-2024-original-0000320193-24-000123-xbrl.zip"
    ) as archive:
        filing_bytes = archive.read("aapl-20240928.htm")
        dts_bytes = {
            filename: archive.read(filename)
            for filename in (
                "aapl-20240928.xsd",
                "aapl-20240928_pre.xml",
                "aapl-20240928_def.xml",
                "aapl-20240928_lab.xml",
                "aapl-20240928_cal.xml",
            )
        }
    taxonomy_cache = tmp_path / "taxonomy-cache"
    taxonomy_cache.mkdir()
    with ZipFile(fixture_root / "arelle-taxonomy-cache-2024.zip") as archive:
        archive.extractall(taxonomy_cache)

    requested_urls = []

    def opener(request, timeout):
        requested_urls.append(request.full_url)
        if request.full_url.endswith("-xbrl.zip"):
            return Response(archive_bytes)
        if request.full_url.endswith("aapl-20240928.htm"):
            return Response(
                direct_filing_bytes
                + b'<script src="/cdn-cgi/challenge-platform/challenge.js"></script>'
            )
        pytest.fail(f"unexpected SEC resource request: {request.full_url}")

    adapter = SecEdgarSourceAdapter(
        SecRequestPolicy(
            user_agent="value-agent test@example.com", min_interval_seconds=0
        ),
        opener=opener,
        sleep=lambda _seconds: None,
    )
    service = SecIngestionService(
        source_adapter=adapter,
        content_store=FilesystemContentStore(tmp_path / "objects"),
        snapshot_repository=FilesystemSnapshotRepository(tmp_path / "snapshots"),
    )
    result = service.ingest_filing(
        identity=IdentityV1(
            issuer_id="0000320193",
            issuer_name="Apple Inc.",
            domicile="US",
            reporting_basis="us-gaap",
            security_id="AAPL",
            share_class="common",
            currency="USD",
        ),
        cik="0000320193",
        accession_number="0000320193-24-000123",
        primary_document="aapl-20240928.htm",
        filing_archive_filename="0000320193-24-000123-xbrl.zip",
        filed_at=datetime(2024, 11, 1, 10, 1, 36, tzinfo=timezone.utc),
        captured_at=datetime(2026, 11, 4, tzinfo=timezone.utc),
        valuation_timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
        parser_version="2.47.4",
        policy_version="source-policy-v1",
        taxonomy_manifest_id="taxonomy-manifest-v1",
        taxonomy_version="us-gaap-2024",
        acquisition_key="a" * 64,
        taxonomy_cache_dir=taxonomy_cache,
        normalized_field="revenue",
        dts_filenames=tuple(dts_bytes),
        mapping=CanonicalMappingV1(
            contract_version="fundamental.v1",
            decision_id="map-revenue-v1",
            source_concept="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            normalized_field="revenue",
            mapping_version="sec-us-gaap-v1",
            confidence="high",
            evidence_refs=("public-sec-review",),
            reviewer="fundamental-service",
            reviewed_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            status="approved",
        ),
    )
    assert result.snapshot.snapshot_id
    assert (
        result.snapshot.validation_profile_id
        == result.parser_report.validation_profile.profile_id
    )
    assert (
        result.snapshot.validation_profile_digest
        == result.parser_report.validation_profile_digest
    )
    assert result.snapshot.acquisition_key == "a" * 64
    filing_record = next(
        record
        for record in result.snapshot.source_records
        if record.source_id == "sec-filing"
    )
    archive_record = next(
        record
        for record in result.snapshot.source_records
        if record.source_id == "sec-filing-archive"
    )
    assert result.parser_report.source_content_hash == filing_record.content_hash
    assert filing_record.content_hash == hashlib.sha256(filing_bytes).hexdigest()
    assert archive_record.content_hash == hashlib.sha256(archive_bytes).hexdigest()
    assert "#member=aapl-20240928.htm" in filing_record.uri
    assert requested_urls == [
        "https://www.sec.gov/Archives/edgar/data/320193/"
        "000032019324000123/0000320193-24-000123-xbrl.zip"
    ]
    assert result.selection.fact is not None
    assert result.selection.fact.quality.value == "verified"
