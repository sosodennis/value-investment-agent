"""Synthetic originals exercise the complete acquisition/mapping/publication path."""

import hashlib
import io
import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile, ZipInfo

import pytest

from fundamental_service.automatic_mapping_batch import AutomaticMappingBatchDecisionV1
from fundamental_service.contracts import QualityStatus
from fundamental_service.data_releases import DataReleaseError
from fundamental_service.ingestion import SecIngestionService
from fundamental_service.metadata import (
    PostgresArtifactStore,
    PostgresContentStore,
    PostgresMetadataStore,
    PostgresSnapshotRepository,
)
from fundamental_service.persistence_recovery import export_backup, restore_backup
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_source import (
    SecEdgarSourceAdapter,
    SecRequestPolicy,
    _SecResponse,
)
from fundamental_service.serialization import canonical_bytes
from fundamental_service.snapshots import FilesystemSnapshotRepository
from fundamental_service.source_acquisition import SecAcquisitionUseCase
from test_automatic_source_mapping import source_case
from test_issuer_operating_release import inventory

PROXY_BYTES = b"<html><body>synthetic definitive proxy</body></html>"


class MemoryAcquisitions:
    def __init__(self):
        self.acquisitions = {}
        self.mappings = {}
        self.audits = []
        self.snapshots = {}

    def publish_mapping(self, mapping):
        previous = self.mappings.setdefault(mapping.decision_id, mapping)
        assert previous == mapping

    def publish_source_audit(self, **value):
        self.audits.append(value)

    def try_acquire_ingestion_lock(self, key):
        return key

    def release_ingestion_lock(self, lease):
        pass

    def get_sec_ingestion(self, key, **kwargs):
        return self.acquisitions.get(key)

    def publish_sec_ingestion(self, **value):
        self.snapshots[value["snapshot"].snapshot_id] = value["snapshot"]
        self.acquisitions[value["acquisition_key"]] = value["result"]
        return value["result"]


def acquisition_case(
    tmp_path,
    monkeypatch,
    *,
    metadata=None,
    artifacts=None,
    content=None,
    repository=None,
    historical_proxy=False,
):
    request, authority, validated, source_artifacts, _ = source_case(tmp_path / "seed")
    metadata = metadata or MemoryAcquisitions()
    artifacts = artifacts or ArtifactStore(tmp_path / "artifacts")
    content = content or authority.content
    for source in validated.captured_sources:
        raw = authority.content.get(source.content_hash, media_type=source.media_type)
        content.put(raw, media_type=source.media_type)
    digest = validated.original.report.taxonomy_cache_hash
    content.put(
        authority.content.get(digest, media_type="application/octet-stream"),
        media_type="application/octet-stream",
    )
    authority = replace(
        authority, metadata=metadata, artifacts=artifacts, content=content
    )
    original = validated.original
    report = original.report
    raw = content.get(original.source.content_hash, media_type="application/xml")
    primary = original.source.uri.rsplit("/", 1)[1]
    schema = Path(primary).stem + ".xsd"
    package = io.BytesIO()
    with ZipFile(package, "w") as archive:
        for name, value in ((primary, raw), (schema, b"synthetic schema")):
            archive.writestr(ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0)), value)
    archive_name = original.source.accession_number + "-xbrl.zip"
    proxy_accession = "0000320193-26-000099"
    proxy_accepted_at = original.source.available_at - timedelta(days=60)
    proxy_document = "proxy.htm"
    proxy_bytes = PROXY_BYTES
    index = canonical_bytes(
        {
            "directory": {
                "item": [
                    {"name": name, "size": str(len(value))}
                    for name, value in (
                        (primary, raw),
                        (proxy_document, proxy_bytes),
                        (schema, b"synthetic schema"),
                        (archive_name, package.getvalue()),
                    )
                ]
            }
        }
    )
    submissions = canonical_bytes(
        {
            "cik": int(request.cik),
            "tickers": [],
            "filings": {
                "recent": {
                    "accessionNumber": [
                        proxy_accession,
                        request.filing.accession_number,
                    ],
                    "filingDate": [
                        proxy_accepted_at.date().isoformat(),
                        original.source.available_at.date().isoformat(),
                    ],
                    "acceptanceDateTime": [
                        proxy_accepted_at.isoformat(),
                        original.source.available_at.isoformat(),
                    ],
                    "form": ["DEF 14A", "10-K"],
                    "primaryDocument": [proxy_document, primary],
                    "isXBRL": [0, 1],
                    "isInlineXBRL": [0, 0],
                }
            },
        }
    )
    submission_data = json.loads(submissions)
    submission_data["filings"]["files"] = []
    history_filename = f"CIK{request.cik}-submissions-001.json"
    history = None
    if historical_proxy:
        recent = submission_data["filings"]["recent"]
        history = canonical_bytes({key: values[:1] for key, values in recent.items()})
        submission_data["filings"]["recent"] = {
            key: values[1:] for key, values in recent.items()
        }
        submission_data["filings"]["files"] = [
            {
                "name": history_filename,
                "filingCount": 1,
                "filingFrom": proxy_accepted_at.date().isoformat(),
                "filingTo": proxy_accepted_at.date().isoformat(),
            }
        ]
    submissions = canonical_bytes(submission_data)
    state = SimpleNamespace(provider_calls=0, parser_calls=0, mode="valid")

    class Provider(SecEdgarSourceAdapter):
        def _request(self, uri, *, deadline_at=None):
            state.provider_calls += 1
            if uri.endswith(history_filename):
                assert history is not None
                value, media = history, "application/json"
            elif "/submissions/" in uri:
                value, media = submissions, "application/json"
            elif uri.endswith("/index.json"):
                value, media = index, "application/json"
            elif uri.endswith(".zip"):
                value, media = package.getvalue(), "application/zip"
            elif uri.endswith("/" + proxy_document):
                value, media = proxy_bytes, "text/html"
            else:
                value, media = raw, "application/xml"
            return _SecResponse(
                value, 200, media, original.source.captured_at, (), len(value)
            )

    def parser(path, **kwargs):
        state.parser_calls += 1
        facts = report.facts
        if state.mode == "wrong_identity":
            facts = tuple(
                f.model_copy(update={"value": "WRONG"})
                if f.concept == "dei:TradingSymbol"
                else f
                for f in facts
            )
        if state.mode == "no_regulatory_evidence":
            return report.model_copy(update={"validation_evidence": ()})
        return report.model_copy(
            update={
                "filing_path": str(path),
                "source_content_hash": kwargs["source_content_hash"],
                "validation_profile": kwargs["profile"],
                "validation_profile_digest": kwargs["profile"].digest(),
                "facts": facts,
            }
        )

    monkeypatch.setattr("fundamental_service.ingestion.parse_filing_offline", parser)
    provider = Provider(
        SecRequestPolicy(
            user_agent="synthetic test@example.com", min_interval_seconds=0
        )
    )
    repository = repository or FilesystemSnapshotRepository(tmp_path / "snapshots")
    ingestion = SecIngestionService(
        source_adapter=provider,
        content_store=content,
        snapshot_repository=repository,
        audit_store=artifacts,
    )
    settings = SimpleNamespace(
        taxonomy_cache_sha256=report.taxonomy_cache_hash,
        taxonomy_manifest_id=request.taxonomy_manifest_id,
        taxonomy_version=request.taxonomy_version,
        supported_filing_years=(2026,),
        supported_filing_forms=("10-K",),
        edgar_plugin_dir=report.validation_profile.edgar_plugin_dir,
        xule_plugin_dir=report.validation_profile.xule_plugin_dir,
        dqc_ruleset_path=report.validation_profile.dqc_ruleset_path,
        edgar_plugin_sha256=report.validation_profile.edgar_plugin_sha256,
        xule_plugin_sha256=report.validation_profile.xule_plugin_sha256,
        dqc_ruleset_sha256=report.validation_profile.dqc_ruleset_sha256,
        dqc_ruleset_catalog=None,
        taxonomy_cache_dir=tmp_path / "synthetic-taxonomy",
        historical_dqc_dir=None,
    )
    use_case = SecAcquisitionUseCase(
        adapter=provider,
        ingestion=ingestion,
        metadata=metadata,
        content_store=content,
        settings=settings,
        authorized_organizations=frozenset({"org"}),
        capture_store=artifacts,
        automatic_mapping_authority=authority,
    )
    return request, use_case, state, metadata, artifacts


def acquire(request, use_case, correlation_id="first"):
    return use_case.execute(
        request,
        caller_principal="caller",
        organization_id="org",
        correlation_id=correlation_id,
        deadline_at=datetime.now(UTC) + timedelta(minutes=1),
    )


@pytest.mark.parametrize("historical_proxy", [False, True])
def test_empty_store_acquires_parses_maps_and_reuses_without_provider_or_parser(
    tmp_path, monkeypatch, historical_proxy
):
    request, use_case, state, metadata, artifacts = acquisition_case(
        tmp_path, monkeypatch, historical_proxy=historical_proxy
    )
    assert not metadata.mappings and not metadata.acquisitions
    result = acquire(request, use_case)
    assert result.snapshot_id and result.canonical_fact_ids
    assert result.quality_status is QualityStatus.ABSTAIN
    assert "non_operating_assets" in result.missing_evidence
    assert "MAPPING_AUTOMATIC_RULE_UNSUPPORTED" in result.issue_codes
    assert result.mapping_evidence_ref
    snapshot = metadata.snapshots[result.snapshot_id]
    proxy_records = [
        record
        for record in snapshot.source_records
        if record.source_id == "sec-supplemental-filing"
    ]
    assert len(proxy_records) == 1
    assert proxy_records[0].accession_number == "0000320193-26-000099"
    assert proxy_records[0].form == "DEF 14A"
    assert proxy_records[0].content_hash == hashlib.sha256(PROXY_BYTES).hexdigest()
    history_records = [
        record
        for record in snapshot.source_records
        if record.source_id == "sec-submissions-history"
    ]
    assert len(history_records) == int(historical_proxy)
    if historical_proxy:
        assert history_records[0].uri.endswith("-submissions-001.json")
    batch = AutomaticMappingBatchDecisionV1.model_validate_json(
        artifacts.read(result.mapping_evidence_ref)
    )
    assert len(batch.roles) == 35 and metadata.mappings
    calls = (state.provider_calls, state.parser_calls)
    assert calls[0] > 0 and calls[1] == 1
    before = inventory(artifacts.root)
    again = acquire(request, use_case, "repeat")
    assert again.reused and again.mapping_evidence_ref == result.mapping_evidence_ref
    assert (
        again.model_copy(
            update={
                "status": result.status,
                "reused": False,
                "correlation_id": result.correlation_id,
            }
        )
        == result
    )
    assert (state.provider_calls, state.parser_calls) == calls
    assert before == inventory(artifacts.root)


def test_command_reuse_is_read_only_without_weakening_authorization_or_api_audit(
    tmp_path, monkeypatch
):
    from fundamental_service.operations import ServiceError

    request, use_case, state, metadata, _ = acquisition_case(tmp_path, monkeypatch)
    original = acquire(request, use_case)
    audits = tuple(metadata.audits)
    calls = state.provider_calls, state.parser_calls

    def execute(organization="org", **kwargs):
        return use_case.execute(
            request,
            caller_principal="caller",
            organization_id=organization,
            correlation_id="read-only-command",
            deadline_at=datetime.now(UTC) + timedelta(minutes=1),
            **kwargs,
        )

    repeated = execute(audit_reuse=False)
    assert repeated.reused and repeated.snapshot_id == original.snapshot_id
    assert tuple(metadata.audits) == audits
    with pytest.raises(ServiceError, match="not authorized"):
        execute("unauthorized", audit_reuse=False)
    assert len(metadata.audits) == len(audits) + 1
    assert metadata.audits[-1]["outcome"] == "INGESTION_NOT_AUTHORIZED"
    execute()
    assert len(metadata.audits) == len(audits) + 2
    assert metadata.audits[-1]["outcome"] == "reused"
    assert calls == (state.provider_calls, state.parser_calls)


@pytest.mark.parametrize("mode", ["wrong_identity", "no_regulatory_evidence"])
def test_original_validation_refusal_never_creates_mappings(
    tmp_path, monkeypatch, mode
):
    from fundamental_service.operations import ServiceError

    request, use_case, state, metadata, _ = acquisition_case(tmp_path, monkeypatch)
    state.mode = mode
    with pytest.raises(ServiceError):
        acquire(request, use_case)
    assert (
        state.parser_calls == 1 and not metadata.mappings and not metadata.acquisitions
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"source_revision": "b" * 40},
        {"mapping_policy_digest": "b" * 64},
        {"evaluator_id": "unknown"},
    ],
)
def test_authority_runtime_refusal_precedes_source_io(tmp_path, monkeypatch, changes):
    request, use_case, state, metadata, artifacts = acquisition_case(
        tmp_path, monkeypatch
    )
    before = inventory(artifacts.root)
    with pytest.raises(DataReleaseError):
        acquire(request.model_copy(update=changes), use_case)
    assert state.provider_calls == state.parser_calls == 0
    assert not metadata.mappings and not metadata.acquisitions
    assert before == inventory(artifacts.root)


def test_postgres_automatic_bootstrap_repeat_reopen_and_empty_store_restore(
    tmp_path, monkeypatch, recovery_databases
):
    database, restored_database = recovery_databases
    metadata = PostgresMetadataStore(database, auto_migrate=True)
    metadata.start()
    root = tmp_path / "durable"
    try:
        content = PostgresContentStore(root / "content", metadata)
        artifacts = PostgresArtifactStore(metadata, content)
        request, use_case, state, _, _ = acquisition_case(
            tmp_path,
            monkeypatch,
            metadata=metadata,
            artifacts=artifacts,
            content=content,
            repository=PostgresSnapshotRepository(metadata),
        )
        first = acquire(request, use_case)
        assert (
            first.quality_status is QualityStatus.ABSTAIN and first.mapping_evidence_ref
        )
        before = inventory(root)
        calls = state.provider_calls, state.parser_calls
        repeated = acquire(request, use_case)
        assert (
            repeated.reused
            and repeated.mapping_evidence_ref == first.mapping_evidence_ref
        )
        assert before == inventory(root) and calls == (
            state.provider_calls,
            state.parser_calls,
        )
        backup = asyncio.run(
            export_backup(
                database,
                root / "content",
                tmp_path / "backups",
                source_revision=request.source_revision,
            )
        )
        expected_digest = hashlib.sha256(
            artifacts.read(first.mapping_evidence_ref)
        ).hexdigest()
    finally:
        metadata.close()
    reopened = PostgresMetadataStore(database, auto_migrate=False)
    reopened.start()
    try:
        use_case.metadata = reopened
        again = acquire(request, use_case)
        assert again.reused and again.canonical_fact_ids == first.canonical_fact_ids
        assert calls == (
            state.provider_calls,
            state.parser_calls,
        ) and before == inventory(root)
    finally:
        reopened.close()
    target = PostgresMetadataStore(restored_database, auto_migrate=True)
    target.start()
    try:
        asyncio.run(
            restore_backup(
                restored_database,
                tmp_path / "restored/content",
                tmp_path / "backups" / backup.manifest_digest,
                manifest_digest=backup.manifest_digest,
            )
        )
        restored_store = PostgresArtifactStore(
            target, PostgresContentStore(tmp_path / "restored/content", target)
        )
        assert (
            hashlib.sha256(restored_store.read(first.mapping_evidence_ref)).hexdigest()
            == expected_digest
        )
        use_case.metadata = target
        restored = acquire(request, use_case)
        assert (
            restored.reused and restored.canonical_fact_ids == first.canonical_fact_ids
        )
        assert calls == (state.provider_calls, state.parser_calls)
    finally:
        target.close()
