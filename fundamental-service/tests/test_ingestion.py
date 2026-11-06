from datetime import datetime, timezone
from email.message import Message
import json
from pathlib import Path
from zipfile import ZipFile

from fundamental_service.contracts import IdentityV1
from fundamental_service.facts import CanonicalMappingV1
from fundamental_service.ingestion import SecIngestionService
from fundamental_service.sec_source import SecEdgarSourceAdapter, SecRequestPolicy
from fundamental_service.snapshots import (
    FilesystemContentStore,
    FilesystemSnapshotRepository,
)


class Response:
    status = 200

    def __init__(self, payload: bytes, *, headers: dict[str, str] | None = None):
        self.payload = payload
        self.headers = Message()
        self.headers["Content-Type"] = "text/html"
        for name, value in (headers or {}).items():
            self.headers[name] = value

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_sec_ingestion_connects_adapter_snapshot_parser_and_fact_selection(
    tmp_path: Path,
):
    fixture_root = Path(__file__).parent / "fixtures" / "sec-edgar"
    filing_bytes = (fixture_root / "apple-2024-original-aapl-20240928.htm").read_bytes()
    archive_path = fixture_root / "apple-2024-original-0000320193-24-000123-xbrl.zip"
    archive_bytes = archive_path.read_bytes()
    with ZipFile(archive_path) as archive:
        primary_bytes = archive.read("aapl-20240928.htm")
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
    index_bytes = json.dumps(
        {
            "directory": {
                "item": [
                    {"name": "aapl-20240928.htm", "size": str(len(primary_bytes) + 1)},
                    {
                        "name": "0000320193-24-000123-xbrl.zip",
                        "size": str(len(archive_bytes)),
                    },
                ]
            }
        }
    ).encode()
    taxonomy_cache = tmp_path / "taxonomy-cache"
    taxonomy_cache.mkdir()
    with ZipFile(fixture_root / "arelle-taxonomy-cache-2024.zip") as archive:
        archive.extractall(taxonomy_cache)

    adapter = SecEdgarSourceAdapter(
        SecRequestPolicy(
            user_agent="value-agent test@example.com", min_interval_seconds=0
        ),
        opener=lambda request, timeout: _ingestion_response(
            request.full_url,
            index_bytes=index_bytes,
            archive_bytes=archive_bytes,
            filing_bytes=filing_bytes,
            dts_bytes=dts_bytes,
        ),
        sleep=lambda _seconds: None,
        clock=lambda: datetime(2026, 11, 4, tzinfo=timezone.utc),
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
        filed_at=datetime(2024, 11, 1, 10, 1, 36, tzinfo=timezone.utc),
        captured_at=datetime(2026, 11, 4, tzinfo=timezone.utc),
        valuation_timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
        parser_version="2.47.4",
        policy_version="source-policy-v1",
        taxonomy_manifest_id="taxonomy-manifest-v1",
        taxonomy_version="us-gaap-2024",
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
    filing_record = next(
        record
        for record in result.snapshot.source_records
        if record.source_id == "sec-filing"
    )
    assert result.parser_report.source_content_hash == filing_record.parser_input_hash
    assert result.parser_report.source_content_hash != filing_record.content_hash
    assert result.selection.fact is not None
    assert result.selection.fact.quality.value == "verified"
    assert result.integrity_evidence.integrity_relation == "normalized"
    assert result.integrity_evidence.raw_content_hash
    assert (
        result.integrity_evidence.archive_member_hash
        == result.integrity_evidence.normalized_content_hash
    )
    assert (
        result.parser_report.source_content_hash
        == result.integrity_evidence.parser_input_hash
    )


def _ingestion_response(
    uri: str,
    *,
    index_bytes: bytes,
    archive_bytes: bytes,
    filing_bytes: bytes,
    dts_bytes: dict[str, bytes],
) -> Response:
    filename = Path(uri).name
    if filename == "index.json":
        return Response(index_bytes, headers={"Content-Type": "application/json"})
    if filename.endswith("-xbrl.zip"):
        return Response(
            archive_bytes,
            headers={
                "Content-Type": "application/zip",
                "Content-Length": str(len(archive_bytes)),
            },
        )
    if filename in dts_bytes:
        return Response(
            dts_bytes[filename], headers={"Content-Type": "application/xml"}
        )
    return Response(
        filing_bytes,
        headers={
            "Content-Type": "text/html",
            "X-Akamai-Transformed": "0 - 0 -",
        },
    )
