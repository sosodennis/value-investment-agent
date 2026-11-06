import hashlib
import json
import os
from datetime import datetime, timezone
from email.message import Message
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from fundamental_service.arelle_parser import (
    ArelleFindingV1,
    ArelleParseReportV1,
    ArelleValidationProfileV1,
    ParsedXbrlFactV1,
    _directory_hash,
)
from fundamental_service.contracts import (
    IdentityV1,
    SecIngestionRejectionEvidenceV1,
)
from fundamental_service.facts import (
    CanonicalMappingV1,
    FilesystemCanonicalFactRepository,
)
from fundamental_service.ingestion import SecIngestionService, _read_sec_xbrl_archive
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_source import SecEdgarSourceAdapter, SecRequestPolicy
from fundamental_service.snapshots import (
    FilesystemContentStore,
    FilesystemSnapshotRepository,
    SnapshotError,
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
    monkeypatch,
):
    fixture_root = Path(__file__).parent / "fixtures" / "sec-edgar"
    direct_filing_bytes = (
        fixture_root / "apple-2024-original-aapl-20240928.htm"
    ).read_bytes()
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
    filing_bytes = direct_filing_bytes
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
    edgar_dir = tmp_path / "edgar"
    xule_dir = tmp_path / "xule"
    edgar_dir.mkdir()
    xule_dir.mkdir()
    (edgar_dir / "plugin.py").write_text("pinned-edgar")
    (xule_dir / "plugin.py").write_text("pinned-xule")
    ruleset = tmp_path / "dqc-ruleset.zip"
    ruleset.write_bytes(b"pinned-dqc")
    profile = ArelleValidationProfileV1(
        profile_id="sec-efm-dqc-fixture-v1",
        validation_mode="sec-efm-dqc",
        edgar_plugin_dir=edgar_dir,
        xule_plugin_dir=xule_dir,
        dqc_ruleset_path=ruleset,
        edgar_plugin_sha256=_directory_hash(edgar_dir),
        xule_plugin_sha256=_directory_hash(xule_dir),
        dqc_ruleset_sha256=hashlib.sha256(ruleset.read_bytes()).hexdigest(),
    )
    parser_state = {"semantic_mismatch": False, "blocking": False}

    def fake_parser(
        path, *, profile, taxonomy_version, taxonomy_cache_dir, source_content_hash
    ):
        value = (
            "391035000001"
            if parser_state["semantic_mismatch"] and Path(path).parent.name == "archive"
            else "391035000000"
        )
        fact = ParsedXbrlFactV1(
            concept="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            value=value,
            context_id="ctx-revenue",
            unit="iso4217:USD",
            entity_identifier="0000320193",
            period_start=datetime(2023, 9, 30, tzinfo=timezone.utc).date(),
            period_end=datetime(2024, 9, 28, tzinfo=timezone.utc).date(),
            is_numeric=True,
            consolidation_scope="consolidated",
        )
        finding = (
            (
                ArelleFindingV1(
                    code="EFM.blockingFixture",
                    severity="error",
                    message="fixture blocking EFM finding",
                ),
            )
            if parser_state["blocking"]
            else ()
        )
        return ArelleParseReportV1(
            filing_path=str(path),
            parser_version=profile.arelle_version,
            taxonomy_version=taxonomy_version,
            validation_profile=profile,
            validation_profile_digest=profile.digest(),
            facts=(fact,),
            findings=finding,
            finding_codes=tuple(item.code for item in finding),
            validation_engines=("sec-efm", "dqc-us"),
            validation_evidence=(
                "strict-sec-efm-profile-selected",
                "dqc-dqcrt-checks-completed",
            ),
            parsed_at=datetime(2026, 11, 4, tzinfo=timezone.utc),
            source_content_hash=source_content_hash,
            taxonomy_cache_hash="a" * 64,
        )

    monkeypatch.setattr(
        "fundamental_service.ingestion.parse_filing_offline", fake_parser
    )

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
    content_store = FilesystemContentStore(tmp_path / "objects")
    snapshot_repository = FilesystemSnapshotRepository(tmp_path / "snapshots")
    audit_store = ArtifactStore(tmp_path / "artifacts")
    service = SecIngestionService(
        source_adapter=adapter,
        content_store=content_store,
        snapshot_repository=snapshot_repository,
        audit_store=audit_store,
    )
    ingestion_args = dict(
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
        profile=profile,
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
    result = service.ingest_filing(**ingestion_args)
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
    assert result.parser_report.source_content_hash == filing_record.parser_input_hash
    assert result.parser_report.source_content_hash != filing_record.content_hash
    assert filing_record.content_hash == hashlib.sha256(filing_bytes).hexdigest()
    assert archive_record.content_hash == hashlib.sha256(archive_bytes).hexdigest()
    assert filing_record.uri.endswith("/aapl-20240928.htm")
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
    replay = service.ingest_filing(**ingestion_args)
    assert replay.snapshot.manifest_digest == result.snapshot.manifest_digest
    assert replay.integrity_evidence == result.integrity_evidence

    rejected_repository = FilesystemSnapshotRepository(tmp_path / "rejected-snapshots")
    rejected_service = SecIngestionService(
        source_adapter=adapter,
        content_store=content_store,
        snapshot_repository=rejected_repository,
        audit_store=audit_store,
    )
    parser_state["semantic_mismatch"] = True
    with pytest.raises(SnapshotError) as semantic_error:
        rejected_service.ingest_filing(**ingestion_args)
    assert semantic_error.value.code == "NORMALIZATION_SEMANTIC_MISMATCH"
    assert (
        rejected_repository.find(
            identity=ingestion_args["identity"],
            valuation_timestamp=ingestion_args["valuation_timestamp"],
        )
        == ()
    )

    parser_state["semantic_mismatch"] = False
    parser_state["blocking"] = True
    with pytest.raises(SnapshotError) as blocking_error:
        rejected_service.ingest_filing(**ingestion_args)
    assert blocking_error.value.code == "PARSER_VALIDATION_BLOCKED"
    with pytest.raises(SnapshotError) as blocking_retry_error:
        rejected_service.ingest_filing(**ingestion_args)
    assert blocking_retry_error.value.code == blocking_error.value.code
    assert blocking_retry_error.value.evidence_ref == blocking_error.value.evidence_ref
    assert (
        rejected_repository.find(
            identity=ingestion_args["identity"],
            valuation_timestamp=ingestion_args["valuation_timestamp"],
        )
        == ()
    )
    raw_hash = hashlib.sha256(filing_bytes).hexdigest()
    assert content_store.get(raw_hash, media_type="text/html") == filing_bytes


def test_sec_ingestion_blocks_real_aapl_efm_finding_without_publishing_facts(
    tmp_path: Path,
):
    required_environment = (
        "ISSUE328_EDGAR_PLUGIN_DIR",
        "ISSUE328_XULE_PLUGIN_DIR",
        "ISSUE328_DQC_RULESET_PATH",
        "ISSUE328_TAXONOMY_CACHE_DIR",
    )
    if not all(os.environ.get(name) for name in required_environment):
        pytest.skip("pinned SEC EFM/DQC runtime paths are not configured")

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
    edgar_dir = Path(os.environ["ISSUE328_EDGAR_PLUGIN_DIR"])
    xule_dir = Path(os.environ["ISSUE328_XULE_PLUGIN_DIR"])
    ruleset = Path(os.environ["ISSUE328_DQC_RULESET_PATH"])
    profile = ArelleValidationProfileV1(
        profile_id="sec-efm-dqc-us-gaap-2024-v1",
        validation_mode="sec-efm-dqc",
        edgar_plugin_dir=edgar_dir,
        xule_plugin_dir=xule_dir,
        dqc_ruleset_path=ruleset,
        edgar_plugin_sha256=_directory_hash(edgar_dir),
        xule_plugin_sha256=_directory_hash(xule_dir),
        dqc_ruleset_sha256=hashlib.sha256(ruleset.read_bytes()).hexdigest(),
    )
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
        clock=lambda: datetime(2026, 11, 6, tzinfo=timezone.utc),
    )
    content_store = FilesystemContentStore(tmp_path / "objects")
    snapshot_repository = FilesystemSnapshotRepository(tmp_path / "snapshots")
    audit_store = ArtifactStore(tmp_path / "audit-artifacts")
    fact_repository = FilesystemCanonicalFactRepository(tmp_path / "facts")
    service = SecIngestionService(
        source_adapter=adapter,
        content_store=content_store,
        snapshot_repository=snapshot_repository,
        audit_store=audit_store,
        fact_repository=fact_repository,
    )
    ingestion_args = dict(
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
        captured_at=datetime(2026, 11, 6, tzinfo=timezone.utc),
        valuation_timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
        parser_version="2.47.4",
        policy_version="source-policy-v1",
        taxonomy_manifest_id="taxonomy-manifest-v1",
        taxonomy_version="us-gaap-2024",
        taxonomy_cache_dir=Path(os.environ["ISSUE328_TAXONOMY_CACHE_DIR"]),
        normalized_field="revenue",
        dts_filenames=tuple(dts_bytes),
        profile=profile,
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

    with pytest.raises(SnapshotError) as error:
        service.ingest_filing(**ingestion_args)

    assert error.value.code == "PARSER_VALIDATION_BLOCKED"
    assert error.value.evidence_ref is not None
    assert (
        snapshot_repository.find(
            identity=ingestion_args["identity"],
            valuation_timestamp=ingestion_args["valuation_timestamp"],
        )
        == ()
    )
    raw_hash = hashlib.sha256(filing_bytes).hexdigest()
    assert content_store.get(raw_hash, media_type="text/html") == filing_bytes
    assert tuple(fact_repository.root.glob("*.json")) == ()

    reopened_audit_store = ArtifactStore(tmp_path / "audit-artifacts")
    rejection_record = reopened_audit_store.get(error.value.evidence_ref)
    rejection = SecIngestionRejectionEvidenceV1.model_validate_json(
        reopened_audit_store.read(error.value.evidence_ref)
    )
    assert rejection_record.retention == "evidence"
    assert rejection.error_code == error.value.code
    assert rejection.integrity_evidence.accession_number == "0000320193-24-000123"
    assert rejection.integrity_evidence.quality_decision == "block"
    assert any(finding.blocks for finding in rejection.integrity_evidence.findings)
    assert len(rejection.parser_replay_digests) == 2
    assert all(len(digest) == 64 for digest in rejection.parser_replay_digests)

    sources_by_id = {source.source_id: source for source in rejection.captured_sources}
    filing_source = sources_by_id["sec-filing"]
    assert filing_source.uri.endswith("/aapl-20240928.htm")
    assert filing_source.accession_number == "0000320193-24-000123"
    assert filing_source.http_status == 200
    assert filing_source.received_size == len(filing_bytes)
    assert filing_source.content_hash == rejection.integrity_evidence.raw_content_hash
    assert filing_source.declared_size is None
    assert "x-akamai-transformed" in {
        name.lower() for name, _value in filing_source.response_headers
    }
    assert sources_by_id["sec-filing-index"].content_hash == (
        rejection.integrity_evidence.archive_index_hash
    )
    assert sources_by_id["sec-filing-archive"].content_hash == (
        rejection.integrity_evidence.archive_hash
    )

    source_hashes = {source.content_hash for source in rejection.captured_sources}
    assert set(rejection_record.dependency_hashes) == source_hashes | {
        rejection.integrity_evidence.normalized_content_hash,
        rejection.integrity_evidence.archive_member_hash,
        rejection.integrity_evidence.validation_profile_digest,
        rejection.integrity_evidence.taxonomy_manifest_hash,
    }
    reopened_content_store = FilesystemContentStore(tmp_path / "objects")
    for source in rejection.captured_sources:
        assert (
            len(
                reopened_content_store.get(
                    source.content_hash, media_type=source.media_type
                )
            )
            == source.received_size
        )
    assert reopened_content_store.get(raw_hash, media_type="text/html") == filing_bytes


def test_sec_ingestion_publishes_real_verified_microsoft_fixture(
    tmp_path: Path,
):
    required_environment = (
        "ISSUE328_EDGAR_PLUGIN_DIR",
        "ISSUE328_XULE_PLUGIN_DIR",
        "ISSUE328_DQC_RULESET_PATH",
        "ISSUE328_TAXONOMY_CACHE_DIR",
    )
    if not all(os.environ.get(name) for name in required_environment):
        pytest.skip("pinned SEC EFM/DQC runtime paths are not configured")

    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "sec-edgar"
        / "microsoft-2024-original-xbrl-test-package.zip"
    )
    with ZipFile(fixture) as archive:
        filing_bytes = archive.read("msft-20240630.htm")
        xsd_bytes = archive.read("msft-20240630.xsd")
    archive_bytes = fixture.read_bytes()
    index_bytes = json.dumps(
        {
            "directory": {
                "item": [
                    {"name": "msft-20240630.htm", "size": str(len(filing_bytes))},
                    {
                        "name": "0000950170-24-087843-xbrl.zip",
                        "size": str(len(archive_bytes)),
                    },
                ]
            }
        }
    ).encode()

    edgar_dir = Path(os.environ["ISSUE328_EDGAR_PLUGIN_DIR"])
    xule_dir = Path(os.environ["ISSUE328_XULE_PLUGIN_DIR"])
    ruleset = Path(os.environ["ISSUE328_DQC_RULESET_PATH"])
    profile = ArelleValidationProfileV1(
        profile_id="sec-efm-dqc-us-gaap-2023-2024-v1",
        validation_mode="sec-efm-dqc",
        edgar_plugin_dir=edgar_dir,
        xule_plugin_dir=xule_dir,
        dqc_ruleset_path=ruleset,
        edgar_plugin_sha256=_directory_hash(edgar_dir),
        xule_plugin_sha256=_directory_hash(xule_dir),
        dqc_ruleset_sha256=hashlib.sha256(ruleset.read_bytes()).hexdigest(),
    )
    adapter = SecEdgarSourceAdapter(
        SecRequestPolicy(
            user_agent="value-agent test@example.com", min_interval_seconds=0
        ),
        opener=lambda request, timeout: _microsoft_ingestion_response(
            request.full_url,
            index_bytes=index_bytes,
            archive_bytes=archive_bytes,
            filing_bytes=filing_bytes,
            xsd_bytes=xsd_bytes,
        ),
        sleep=lambda _seconds: None,
        clock=lambda: datetime(2026, 11, 6, tzinfo=timezone.utc),
    )
    content_store = FilesystemContentStore(tmp_path / "objects")
    snapshot_repository = FilesystemSnapshotRepository(tmp_path / "snapshots")
    service = SecIngestionService(
        source_adapter=adapter,
        content_store=content_store,
        snapshot_repository=snapshot_repository,
        audit_store=ArtifactStore(tmp_path / "artifacts"),
    )
    ingestion_args = dict(
        identity=IdentityV1(
            issuer_id="0000789019",
            issuer_name="Microsoft Corporation",
            domicile="US",
            reporting_basis="us-gaap",
            security_id="MSFT",
            share_class="common",
            currency="USD",
        ),
        cik="0000789019",
        accession_number="0000950170-24-087843",
        primary_document="msft-20240630.htm",
        filed_at=datetime(2024, 7, 30, 20, 6, 22, tzinfo=timezone.utc),
        captured_at=datetime(2026, 11, 6, tzinfo=timezone.utc),
        valuation_timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
        parser_version="2.47.4",
        policy_version="source-policy-v1",
        taxonomy_manifest_id="sec-us-gaap-2023-2024-public-bundle",
        taxonomy_version="us-gaap-2023-2024",
        taxonomy_cache_dir=Path(os.environ["ISSUE328_TAXONOMY_CACHE_DIR"]),
        normalized_field="revenue",
        dts_filenames=("msft-20240630.xsd",),
        profile=profile,
        mapping=CanonicalMappingV1(
            contract_version="fundamental.v1",
            decision_id="map-msft-revenue-v1",
            source_concept="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            normalized_field="revenue",
            mapping_version="sec-us-gaap-v1",
            confidence="high",
            evidence_refs=("sec-archive-msft-2024",),
            reviewer="fundamental-service",
            reviewed_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            status="approved",
        ),
    )

    result = service.ingest_filing(**ingestion_args)
    assert len(result.parser_report.facts) >= 1800
    assert result.parser_report.blocking_finding_codes() == ()
    assert result.selection.fact is not None
    assert result.selection.fact.quality.value == "verified"
    assert result.snapshot.sec_integrity_evidence is not None
    assert result.integrity_evidence.integrity_relation == "exact"
    assert result.integrity_evidence.normalization_policy_id is None
    assert result.integrity_evidence.network_attempt_count == 0
    assert result.integrity_evidence.archive_hash

    replay = service.ingest_filing(**ingestion_args)
    assert replay.snapshot.manifest_digest == result.snapshot.manifest_digest
    assert replay.integrity_evidence == result.integrity_evidence
    assert (
        content_store.get(
            result.integrity_evidence.raw_content_hash, media_type="text/html"
        )
        == filing_bytes
    )
    assert (
        content_store.get(
            result.integrity_evidence.archive_hash, media_type="application/zip"
        )
        == archive_bytes
    )
    assert (
        len(
            snapshot_repository.find(
                identity=ingestion_args["identity"],
                valuation_timestamp=ingestion_args["valuation_timestamp"],
            )
        )
        == 1
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


def _microsoft_ingestion_response(
    uri: str,
    *,
    index_bytes: bytes,
    archive_bytes: bytes,
    filing_bytes: bytes,
    xsd_bytes: bytes,
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
    if filename == "msft-20240630.xsd":
        return Response(xsd_bytes, headers={"Content-Type": "application/xml"})
    return Response(filing_bytes, headers={"Content-Type": "text/html"})
