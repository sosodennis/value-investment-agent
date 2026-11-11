import hashlib
import json
import os
from datetime import date, datetime, timezone
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
from fundamental_service.contracts import IdentityV1, Severity, SecIntegrityEvidenceV1
from fundamental_service.historical_dqc import V1_PROFILE, V3_PROFILE
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


@pytest.mark.parametrize(
    "historical", (None, V1_PROFILE, V3_PROFILE), ids=("modern", "v1", "v3")
)
def test_sec_ingestion_connects_adapter_snapshot_parser_and_fact_selection(
    tmp_path: Path,
    monkeypatch,
    historical,
):
    fixture_root = Path(__file__).parent / "fixtures" / "sec-edgar"
    direct_filing_bytes = (
        fixture_root / "apple-2024-original-aapl-20240928.htm"
    ).read_bytes()
    archive_path = fixture_root / "apple-2024-original-0000320193-24-000123-xbrl.zip"
    archive_bytes = archive_path.read_bytes()
    with ZipFile(archive_path) as archive:
        primary_bytes = archive.read("aapl-20240928.htm")
        graphic_bytes = {
            name: archive.read(name)
            for name in ("aapl-20240928_g1.jpg", "aapl-20240928_g2.jpg")
        }
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
        profile_id=historical.profile_id if historical else "sec-efm-dqc-fixture-v1",
        dqc_version=historical.dqc_version if historical else "v31.0.3",
        historical_dqc_dir=tmp_path if historical else None,
        historical_dqc_sha256=historical.source_sha256 if historical else None,
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
        path,
        *,
        profile,
        taxonomy_version,
        taxonomy_cache_dir,
        source_content_hash,
        deadline_at=None,
    ):
        for name, expected in graphic_bytes.items():
            assert (Path(path).parent / name).read_bytes() == expected
        value = (
            "391035000001"
            if parser_state["semantic_mismatch"] and Path(path).parent.name == "archive"
            else "391035000000"
        )
        fact = ParsedXbrlFactV1(
            concept="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            namespace_uri="http://fasb.org/us-gaap/2024",
            value=value,
            context_id="ctx-revenue",
            unit="iso4217:USD",
            entity_identifier="0000320193",
            entity_scheme="http://www.sec.gov/CIK",
            period_start=datetime(2023, 9, 30, tzinfo=timezone.utc).date(),
            period_end=datetime(2024, 9, 28, tzinfo=timezone.utc).date(),
            is_numeric=True,
            consolidation_scope="consolidated",
        )
        finding = (
            (
                ArelleFindingV1(
                    code="DQC.US.0015.2098",
                    severity="warning",
                    rule_severity="error",
                    message="fixture official DQC error demoted by EDGAR",
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
                historical.completion_marker
                if historical
                else "dqc-dqcrt-checks-completed",
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
    preparation_args = {
        key: value
        for key, value in ingestion_args.items()
        if key not in {"normalized_field", "mapping"}
    }
    preparation_args["mappings"] = (
        ingestion_args["mapping"].model_copy(
            update={"status": "provisional", "confidence": "unresolved"}
        ),
    )
    prepared = service.prepare_filing(**preparation_args)
    assert prepared.facts and all(
        fact.quality.value == "provisional" for fact in prepared.facts
    )
    assert not tuple(snapshot_repository.root.glob("*.json"))
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
    expected_marker = (
        historical.completion_marker if historical else "dqc-dqcrt-checks-completed"
    )
    for marker in (
        V1_PROFILE.completion_marker,
        V3_PROFILE.completion_marker,
        "dqc-dqcrt-checks-completed",
        "dqc-not-completed",
    ):
        if marker == expected_marker:
            continue
        payload = result.integrity_evidence.model_dump()
        payload["validation_evidence"] = ("strict-sec-efm-profile-selected", marker)
        with pytest.raises(ValueError, match="requires EFM and DQC evidence"):
            SecIntegrityEvidenceV1.model_validate(payload)

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
    assert blocking_error.value.evidence_ref is not None
    rejection = json.loads(audit_store.read(blocking_error.value.evidence_ref))
    assert rejection["integrity_evidence"]["findings"] == [
        {
            "code": "DQC.US.0015.2098",
            "severity": "warning",
            "rule_severity": "error",
            "blocks": True,
        }
    ]
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

    parser_state["blocking"] = False
    missing_field_mapping = ingestion_args["mapping"].model_copy(
        update={
            "decision_id": "map-missing-field-v1",
            "normalized_field": "cash_and_equivalents",
            "source_concept": "us-gaap:CashAndCashEquivalentsAtCarryingValue",
        }
    )
    prepare_args = {
        key: value
        for key, value in ingestion_args.items()
        if key not in {"normalized_field", "mapping"}
    }
    prepare_args.update(
        {
            "acquisition_key": "b" * 64,
            "policy_version": "source-policy-missing-field-v1",
            "mappings": (ingestion_args["mapping"], missing_field_mapping),
        }
    )
    missing_field_result = service.prepare_filing(**prepare_args)
    missing_field_issue = next(
        issue for issue in missing_field_result.issues if issue.code == "FACT_NOT_FOUND"
    )
    assert missing_field_result.missing_fields == ("cash_and_equivalents",)
    assert missing_field_issue.severity is Severity.ERROR

    historical_args = {
        **prepare_args,
        "identity_basis": "original-filing-dei-v1",
        "identity_ticker": "AAPL",
        "accepted_at": ingestion_args["filed_at"],
    }
    rejected_service = SecIngestionService(
        source_adapter=adapter,
        content_store=content_store,
        snapshot_repository=rejected_repository,
        audit_store=audit_store,
    )
    with pytest.raises(SnapshotError) as identity_error:
        rejected_service.prepare_filing(**historical_args)
    assert identity_error.value.code == "HISTORICAL_IDENTITY_MISSING"
    assert identity_error.value.evidence_ref
    evidence = json.loads(audit_store.read(identity_error.value.evidence_ref))
    assert evidence["identity_basis"] == "original-filing-dei-v1"
    assert evidence["outcome"] == "refused"
    assert evidence["source_hash"] == hashlib.sha256(filing_bytes).hexdigest()
    assert evidence["current_ticker_or_survival_data_used"] is False
    assert evidence["facts"] == []
    before = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*") if p.is_file()}
    with pytest.raises(SnapshotError) as retry_error:
        rejected_service.prepare_filing(**historical_args)
    assert retry_error.value.evidence_ref == identity_error.value.evidence_ref
    assert before == {
        p: p.stat().st_mtime_ns for p in tmp_path.rglob("*") if p.is_file()
    }
    assert not rejected_repository.find(
        identity=ingestion_args["identity"],
        valuation_timestamp=ingestion_args["valuation_timestamp"],
    )

    original_values = {
        "EntityCentralIndexKey": "0000320193",
        "EntityRegistrantName": "Apple Inc.",
        "EntityIncorporationStateCountryCode": "CA",
        "DocumentType": "10-K",
        "DocumentPeriodEndDate": "2024-09-28",
        "TradingSymbol": "AAPL",
        "Security12bTitle": "Common Stock",
    }

    def identity_parser(path, **kwargs):
        report = fake_parser(path, **kwargs)
        identity_facts = tuple(
            ParsedXbrlFactV1(
                concept=f"dei:{name}",
                namespace_uri="http://xbrl.sec.gov/dei/2024",
                value=value,
                context_id="original-annual",
                entity_scheme="http://www.sec.gov/CIK",
                entity_identifier="0000320193",
                period_start=date(2023, 10, 1),
                period_end=date(2024, 9, 28),
            )
            for name, value in original_values.items()
        )
        return report.model_copy(update={"facts": (*report.facts, *identity_facts)})

    monkeypatch.setattr(
        "fundamental_service.ingestion.parse_filing_offline", identity_parser
    )
    historical_args["identity"] = historical_args["identity"].model_copy(
        update={"share_class": "Common Stock"}
    )
    matched = rejected_service.prepare_filing(**historical_args)
    assert matched.identity_evidence_ref
    proof = json.loads(audit_store.read(matched.identity_evidence_ref))
    assert proof["outcome"] == "matched"
    assert proof["error_code"] is None
    assert len(proof["facts"]) == 7
    before = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*") if p.is_file()}
    repeated = rejected_service.prepare_filing(**historical_args)
    assert repeated.identity_evidence_ref == matched.identity_evidence_ref
    assert repeated.snapshot.manifest_digest == matched.snapshot.manifest_digest
    assert before == {
        p: p.stat().st_mtime_ns for p in tmp_path.rglob("*") if p.is_file()
    }


def test_sec_ingestion_publishes_aapl_with_archived_graphics_staged_offline(
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

    result = service.ingest_filing(**ingestion_args)

    assert result.integrity_evidence.quality_decision == "pass"
    assert result.integrity_evidence.integrity_relation == "normalized"
    assert result.integrity_evidence.archive_member_hash == (
        result.integrity_evidence.normalized_content_hash
    )
    assert result.integrity_evidence.normalized_fact_count >= 1000
    assert result.integrity_evidence.normalized_fact_count == (
        result.integrity_evidence.archive_fact_count
    )
    assert result.integrity_evidence.normalized_fact_digest == (
        result.integrity_evidence.archive_fact_digest
    )
    assert result.parser_report.network_attempt_count == 0
    assert result.parser_report.blocking_finding_codes() == ()
    assert "EFM.5.02.05.graphicFileError" not in result.parser_report.finding_codes
    assert result.selection.fact is not None
    assert result.selection.fact.quality.value == "verified"
    assert (
        len(
            snapshot_repository.find(
                identity=ingestion_args["identity"],
                valuation_timestamp=ingestion_args["valuation_timestamp"],
            )
        )
        == 1
    )
    raw_hash = hashlib.sha256(filing_bytes).hexdigest()
    assert result.integrity_evidence.raw_content_hash == raw_hash
    assert content_store.get(raw_hash, media_type="text/html") == filing_bytes
    assert len(tuple(fact_repository.root.glob("*.json"))) == 1

    replay = service.ingest_filing(**ingestion_args)
    assert replay.snapshot.manifest_digest == result.snapshot.manifest_digest
    assert replay.integrity_evidence == result.integrity_evidence


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
        archive_member = archive.read("msft-20240630.htm")
        xsd_bytes = archive.read("msft-20240630.xsd")
    edge_script = b'<script type="text/javascript"  src="/edge/path/token"></script>'
    filing_bytes = (
        archive_member[: -len(b"</body>\n</html>")]
        + edge_script
        + b"</body>\n</html>\n"
    )
    archive_bytes = fixture.read_bytes()
    index_bytes = json.dumps(
        {
            "directory": {
                "item": [
                    {
                        "name": "msft-20240630.htm",
                        "size": str(len(archive_member) + 1),
                    },
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
    assert result.integrity_evidence.integrity_relation == "normalized"
    assert (
        result.integrity_evidence.normalization_policy_id
        == "sec-edgar-akamai-trailing-script-v2"
    )
    assert len(result.integrity_evidence.removed_ranges) == 2
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
            result.integrity_evidence.normalized_content_hash, media_type="text/html"
        )
        == archive_member
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
    return Response(
        filing_bytes,
        headers={
            "Content-Type": "text/html",
            "X-Akamai-Transformed": "0 - 0 -",
        },
    )
