import os
from asyncio import CancelledError
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from email.message import Message
from io import BytesIO
from pathlib import Path
from typing import NoReturn
from urllib.request import Request
from urllib.response import addinfourl

import pytest
from fastapi.testclient import TestClient
from fundamental_service import app as runtime_app
from fundamental_service import fiscal_runtime, sec_source
from fundamental_service.annual_discovery import AnnualDiscoveryRequestV1
from fundamental_service.app import create_runtime_app
from fundamental_service.arelle_parser import _directory_hash
from fundamental_service.data_releases import DataReleaseTrustRootsV1
from fundamental_service.fiscal_discovery import FiscalDiscoveryRequestV1
from fundamental_service.metadata import PostgresMetadataStore
from fundamental_service.replay import ArtifactRecordV1
from fundamental_service.sec_capture import sec_response_artifact_id
from fundamental_service.serialization import canonical_bytes
from fundamental_service.snapshots import SnapshotError
from fundamental_service.source_acquisition import SecAcquisitionUseCase

SOURCE_REVISION = "293c068cc8cca6a4329b13a21f88ce93c1b47326"
FISCAL_PREFIX = "FUNDAMENTAL_FISCAL_SEC_"


@pytest.fixture
def sec_resources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[str, str]:
    monkeypatch.setenv("FUNDAMENTAL_SERVICE_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv(
        "FUNDAMENTAL_SERVICE_DATABASE_URL",
        "postgresql://unused:unused@localhost/unused",
    )
    monkeypatch.setenv("FUNDAMENTAL_SERVICE_TOKEN", "test-service-token")
    monkeypatch.setenv("FUNDAMENTAL_SEC_USER_AGENT", "Fixture sec@example.test")
    monkeypatch.delenv("FUNDAMENTAL_SOURCE_USE_POLICY_FILE", raising=False)
    monkeypatch.delenv("FUNDAMENTAL_SOURCE_USE_POLICY_DIGEST", raising=False)
    for variable in (
        "FUNDAMENTAL_DATA_RELEASE_TRUST_ROOTS_FILE",
        "FUNDAMENTAL_MODEL_TRUST_ROOTS_FILE",
        "FUNDAMENTAL_MODEL_RELEASE_DEPLOYMENT_FILE",
        "FUNDAMENTAL_SEC_DQC_RULESET_CATALOG_PATH",
        "FUNDAMENTAL_SEC_DQC_V18_RULESET_CATALOG_PATH",
        "FUNDAMENTAL_SEC_HISTORICAL_DQC_DIR",
        "FUNDAMENTAL_SEC_HISTORICAL_DQC_SHA256",
    ):
        monkeypatch.delenv(variable, raising=False)

    def pinned_directory(variable: str, directory: str) -> str:
        path = tmp_path / directory
        path.mkdir()
        (path / "fixture.xml").write_text(f"<{directory}/>", encoding="utf-8")
        digest = _directory_hash(path)
        monkeypatch.setenv(f"{variable}_DIR", str(path))
        monkeypatch.setenv(f"{variable}_SHA256", digest)
        return digest

    annual_digest = pinned_directory("FUNDAMENTAL_SEC_TAXONOMY_CACHE", "annual")
    fiscal_digest = pinned_directory("FUNDAMENTAL_FISCAL_SEC_TAXONOMY_CACHE", "fiscal")
    monkeypatch.setattr(fiscal_runtime, "FISCAL_TAXONOMY_CACHE_SHA256", fiscal_digest)
    pinned_directory("FUNDAMENTAL_SEC_EDGAR_PLUGIN", "edgar")
    pinned_directory("FUNDAMENTAL_SEC_XULE_PLUGIN", "xule")
    ruleset = tmp_path / "ruleset.zip"
    ruleset.touch()
    monkeypatch.setenv("FUNDAMENTAL_SEC_DQC_RULESET_PATH", str(ruleset))
    monkeypatch.setenv(
        "FUNDAMENTAL_SEC_DQC_RULESET_SHA256",
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )
    monkeypatch.setenv("FUNDAMENTAL_SEC_TAXONOMY_MANIFEST_ID", "annual-fixture")
    monkeypatch.setenv("FUNDAMENTAL_SEC_TAXONOMY_VERSION", "us-gaap-2024")
    monkeypatch.setenv("FUNDAMENTAL_SEC_SUPPORTED_FILING_YEARS", "2023,2024")
    monkeypatch.setenv("FUNDAMENTAL_SEC_SUPPORTED_FILING_FORMS", "10-K,10-K/A")
    monkeypatch.setenv("FUNDAMENTAL_FISCAL_SEC_TAXONOMY_MANIFEST_ID", "fiscal-fixture")
    monkeypatch.setenv("FUNDAMENTAL_FISCAL_SEC_TAXONOMY_VERSION", "us-gaap-2025")
    monkeypatch.setenv("FUNDAMENTAL_FISCAL_SEC_SUPPORTED_FILING_YEARS", "2024,2025")
    monkeypatch.setenv("FUNDAMENTAL_FISCAL_SEC_SUPPORTED_FILING_FORMS", "10-Q,10-K")
    return annual_digest, fiscal_digest


@pytest.fixture
def runtime_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[list[PostgresMetadataStore]]:
    stores: list[PostgresMetadataStore] = []

    def track_metadata(
        database_url: str,
        *,
        auto_migrate: bool,
        data_release_trust_roots: DataReleaseTrustRootsV1 | None,
    ) -> PostgresMetadataStore:
        store = PostgresMetadataStore(
            database_url,
            auto_migrate=auto_migrate,
            data_release_trust_roots=data_release_trust_roots,
        )
        stores.append(store)
        assert store._runner._thread.is_alive()
        return store

    monkeypatch.setattr(runtime_app, "PostgresMetadataStore", track_metadata)
    try:
        yield stores
    finally:
        for store in stores:
            store.close()


def test_runtime_releases_metadata_when_content_root_is_file(
    sec_resources: tuple[str, str],
    runtime_metadata: list[PostgresMetadataStore],
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    data_root.touch()

    with pytest.raises(NotADirectoryError) as failure:
        create_runtime_app()

    assert failure.value.filename == str(data_root / "content")
    [store] = runtime_metadata
    assert not store._runner._thread.is_alive()


def test_runtime_releases_metadata_when_app_construction_is_cancelled(
    sec_resources: tuple[str, str],
    runtime_metadata: list[PostgresMetadataStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancellation = CancelledError()

    def cancel_app(**_kwargs: object) -> NoReturn:
        raise cancellation

    monkeypatch.setattr(runtime_app, "create_app", cancel_app)

    with pytest.raises(CancelledError) as failure:
        create_runtime_app()

    assert failure.value is cancellation
    [store] = runtime_metadata
    assert not store._runner._thread.is_alive()


def test_runtime_metadata_lives_until_app_shutdown(
    sec_resources: tuple[str, str],
    runtime_metadata: list[PostgresMetadataStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(PostgresMetadataStore, "start", lambda _store: None)
    monkeypatch.setattr(
        PostgresMetadataStore, "publish_model", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        PostgresMetadataStore, "publish_policy", lambda *_args, **_kwargs: None
    )

    app = create_runtime_app()
    [store] = runtime_metadata
    thread = store._runner._thread
    assert app.state.metadata_store is store
    assert thread.is_alive()
    with TestClient(app):
        assert thread.is_alive()
    assert not thread.is_alive()


def test_runtime_app_preserves_annual_and_fiscal_owners(
    sec_resources: tuple[str, str],
) -> None:
    app = create_runtime_app()
    try:
        annual = app.state.sec_acquisition
        fiscal = getattr(app.state, "fiscal_sec_acquisition", None)
        assert isinstance(annual, SecAcquisitionUseCase)
        assert isinstance(fiscal, SecAcquisitionUseCase)
        assert annual is not fiscal
        assert annual.adapter is not fiscal.adapter
        assert annual.settings is not fiscal.settings
        assert annual.metadata is fiscal.metadata is app.state.metadata_store
        application = app.state.application
        assert annual.content_store is fiscal.content_store is application.content_store
        assert annual.ingestion.builder.repository is application.snapshot_repository
        assert fiscal.ingestion.builder.repository is application.snapshot_repository
        assert annual.ingestion.fact_repository is application.fact_repository
        assert fiscal.ingestion.fact_repository is application.fact_repository
        assert application.statement_originals._validator is annual
        assert fiscal.automatic_mapping_authority is None
        annual_pin = annual.original_validation_runtime(
            declared_source_revision=SOURCE_REVISION
        )
        fiscal_pin = fiscal.original_validation_runtime(
            declared_source_revision=SOURCE_REVISION
        )
        assert (
            annual_pin.taxonomy_manifest_id,
            annual_pin.taxonomy_version,
            annual_pin.taxonomy_cache_sha256,
            annual_pin.supported_filing_years,
            annual_pin.supported_filing_forms,
        ) == (
            "annual-fixture",
            "us-gaap-2024",
            sec_resources[0],
            (2023, 2024),
            ("10-K", "10-K/A"),
        )
        assert (
            fiscal_pin.taxonomy_manifest_id,
            fiscal_pin.taxonomy_version,
            fiscal_pin.taxonomy_cache_sha256,
            fiscal_pin.supported_filing_years,
            fiscal_pin.supported_filing_forms,
        ) == (
            "fiscal-fixture",
            "us-gaap-2025",
            sec_resources[1],
            (2024, 2025),
            ("10-K", "10-Q"),
        )
    finally:
        app.state.metadata_store.close()


def test_runtime_owners_publish_separate_receipts_and_share_sec_pacing(
    sec_resources: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    cik = "0000789019"
    cutoff = datetime(2025, 1, 1, tzinfo=UTC)
    deadline = datetime.now(UTC) + timedelta(seconds=30)
    payload = canonical_bytes(
        {
            "cik": cik,
            "filings": {
                "recent": {
                    "accessionNumber": ["0000950170-24-000001"],
                    "filingDate": ["2024-08-01"],
                    "acceptanceDateTime": ["2024-08-01T12:00:00Z"],
                    "reportDate": ["2024-06-30"],
                    "form": ["10-K"],
                    "primaryDocument": ["filing.htm"],
                    "isXBRL": [1],
                    "isInlineXBRL": [1],
                }
            },
        }
    )
    paced_by: list[PostgresMetadataStore] = []
    opened: list[str] = []

    def reserve_slot(metadata: PostgresMetadataStore, interval: float) -> float:
        assert interval > 0
        paced_by.append(metadata)
        return 0.0

    def open_sec(request: Request, *, timeout: float) -> addinfourl:
        assert request.get_header("User-agent") == "Fixture sec@example.test"
        opened.append(request.full_url)
        headers = Message()
        headers["Content-Type"] = "application/json"
        return addinfourl(BytesIO(payload), headers, request.full_url, code=200)

    monkeypatch.setattr(
        PostgresMetadataStore, "reserve_sec_provider_request_slot", reserve_slot
    )
    monkeypatch.setattr(sec_source, "_open_sec", open_sec)
    app = create_runtime_app()
    metadata = app.state.metadata_store
    records: dict[str, ArtifactRecordV1] = {}

    def get_artifact(artifact_id: str) -> ArtifactRecordV1:
        if artifact_id not in records:
            raise SnapshotError("ARTIFACT_NOT_FOUND", "test artifact is absent")
        return records[artifact_id]

    def publish_artifact(record: ArtifactRecordV1, **_kwargs: object) -> bool:
        assert record.artifact_id not in records
        records[record.artifact_id] = record
        return True

    monkeypatch.setattr(metadata, "get_artifact", get_artifact)
    monkeypatch.setattr(metadata, "publish_artifact", publish_artifact)
    monkeypatch.setattr(metadata, "register_content", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(metadata, "try_acquire_ingestion_lock", lambda key: key)
    monkeypatch.setattr(metadata, "release_ingestion_lock", lambda _lease: None)
    try:
        annual = app.state.application.statement_originals._discovery
        fiscal = app.state.fiscal_sec_acquisition.fiscal_discovery()
        annual_request = AnnualDiscoveryRequestV1(
            cik=cik,
            valuation_timestamp=cutoff,
            declared_source_revision=SOURCE_REVISION,
            supported_filing_years=(2023, 2024),
        )
        fiscal_request = FiscalDiscoveryRequestV1(
            cik=cik,
            valuation_timestamp=cutoff,
            declared_source_revision=SOURCE_REVISION,
            supported_filing_years=(2024, 2025),
        )
        annual_evidence, annual_publication = annual.execute(
            annual_request, deadline_at=deadline
        )
        fiscal_evidence, fiscal_publication = fiscal.execute(
            fiscal_request, deadline_at=deadline
        )

        uri = f"https://data.sec.gov/submissions/CIK{cik}.json"
        assert opened == [uri, uri]
        assert paced_by == [metadata, metadata]
        assert annual_publication.wrote and fiscal_publication.wrote
        assert annual_publication.artifact.artifact_id.startswith("annual-discovery:")
        assert fiscal_publication.artifact.artifact_id.startswith("fiscal-discovery:")
        annual_receipt = annual_evidence.sources[0].receipt
        fiscal_receipt = fiscal_evidence.sources[0].receipt
        assert annual_receipt is not None and fiscal_receipt is not None
        assert annual_receipt.scope.protocol == "sec-original-annual-discovery-v1"
        assert fiscal_receipt.scope.protocol == "sec-original-fiscal-discovery-v1"
        assert annual_receipt.content_hash == fiscal_receipt.content_hash
        annual_id = sec_response_artifact_id(annual_receipt.scope, uri)
        fiscal_id = sec_response_artifact_id(fiscal_receipt.scope, uri)
        assert annual_id != fiscal_id
        assert records[annual_id].content_hash != records[fiscal_id].content_hash
        assert annual.read(annual_publication.artifact.artifact_id) == annual_evidence
        assert (
            fiscal.read(fiscal_publication.artifact.artifact_id, deadline_at=deadline)
            == fiscal_evidence
        )
    finally:
        metadata.close()


def test_runtime_without_fiscal_configuration_preserves_annual_owner(
    sec_resources: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in tuple(os.environ):
        if name.startswith(FISCAL_PREFIX):
            monkeypatch.delenv(name)

    app = create_runtime_app()
    try:
        assert app.state.fiscal_sec_acquisition is None
        annual = app.state.sec_acquisition
        assert (
            annual.original_validation_runtime(
                declared_source_revision=SOURCE_REVISION
            ).taxonomy_cache_sha256
            == sec_resources[0]
        )
        assert app.state.application.statement_originals._validator is annual
    finally:
        app.state.metadata_store.close()


@pytest.mark.parametrize(
    ("variable", "value", "error"),
    [
        ("TAXONOMY_MANIFEST_ID", None, "TAXONOMY_MANIFEST_ID"),
        ("TAXONOMY_VERSION", "  ", "TAXONOMY_VERSION"),
        ("SUPPORTED_FILING_YEARS", "twenty", "SUPPORTED_FILING_YEARS"),
        ("SUPPORTED_FILING_FORMS", "20-F", "SUPPORTED_FILING_FORMS"),
        ("TAXONOMY_CACHE_SHA256", "a" * 64, "TAXONOMY_CACHE_SHA256"),
    ],
)
def test_runtime_rejects_invalid_fiscal_environment(
    sec_resources: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
    value: str | None,
    error: str,
) -> None:
    if value is None:
        monkeypatch.delenv(FISCAL_PREFIX + variable)
    else:
        monkeypatch.setenv(FISCAL_PREFIX + variable, value)
    with pytest.raises(ValueError, match=FISCAL_PREFIX + error):
        create_runtime_app()


def test_runtime_rejects_changed_fiscal_cache_bytes(
    sec_resources: tuple[str, str], tmp_path: Path
) -> None:
    (tmp_path / "fiscal" / "fixture.xml").write_text("<wrong/>", encoding="utf-8")
    with pytest.raises(
        ValueError, match="pinned SEC taxonomy cache hash does not match"
    ):
        create_runtime_app()


def test_runtime_rejects_fiscal_without_required_shared_pin(
    sec_resources: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FUNDAMENTAL_SEC_EDGAR_PLUGIN_SHA256")
    with pytest.raises(ValueError, match="requires .*shared EDGAR, XULE and DQC pins"):
        create_runtime_app()
