from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fundamental_service.app import create_app
from fundamental_service.contracts import IdentityV1, SourceRole
from fundamental_service.snapshots import (
    CapturedSource,
    FilesystemContentStore,
    FilesystemSnapshotRepository,
    LegalSource,
    SnapshotBuilder,
    SnapshotError,
    SourceRegister,
    select_available_sources,
)
from fundamental_service.testsupport import auth_headers, make_internal_envelope


def identity() -> IdentityV1:
    return IdentityV1(
        issuer_id="CIK0000000001",
        issuer_name="Example Corp",
        domicile="US",
        reporting_basis="us-gaap",
        security_id="EXAMPLE-COMMON",
        share_class="common",
        currency="USD",
    )


def build(tmp_path: Path, captured_at: datetime):
    register = SourceRegister(
        (LegalSource("sec", SourceRole.FILING, "sec-terms", "indefinite"),)
    )
    register.require("sec")
    builder = SnapshotBuilder(
        FilesystemContentStore(tmp_path / "objects"),
        FilesystemSnapshotRepository(tmp_path / "manifests"),
        source_register=register,
    )
    return builder.build(
        identity=identity(),
        valuation_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        captured_at=captured_at,
        parser_version="fixture-parser-v1",
        policy_version="source-policy-v1",
        sources=(
            CapturedSource(
                source_id="sec",
                uri="https://example.test/10-k.html",
                role=SourceRole.FILING,
                content=b"same immutable filing",
                media_type="text/html",
                http_status=200,
                available_at=datetime(2025, 12, 1, tzinfo=timezone.utc),
                filed_at=datetime(2025, 12, 1, tzinfo=timezone.utc),
                accession_number="0000000001-25-000001",
                form="10-K",
            ),
            CapturedSource(
                source_id="sec",
                uri="https://example.test/later-amendment.html",
                role=SourceRole.FILING,
                content=b"later amendment",
                media_type="text/html",
                http_status=200,
                available_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
                filed_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
                accession_number="0000000001-26-000001",
                form="10-K/A",
                is_amendment=True,
                amends_accession="0000000001-25-000001",
                amendment_scope="unrelated",
            ),
        ),
    )


def test_same_bytes_have_stable_snapshot_id_and_manifest_is_immutable(tmp_path: Path):
    first = build(tmp_path, datetime(2026, 1, 2, tzinfo=timezone.utc))
    second = build(tmp_path / "second", datetime(2026, 1, 3, tzinfo=timezone.utc))
    assert first.snapshot_id != second.snapshot_id
    assert first.source_records[0].content_hash == second.source_records[0].content_hash
    assert len(select_available_sources(first)) == 1
    repository = FilesystemSnapshotRepository(tmp_path / "manifests")
    repository.publish(first)
    repository.publish(first)
    with pytest.raises(SnapshotError, match="unavailable"):
        repository.get("../escape")


def test_source_register_and_missing_fixture_fail_explicitly():
    with pytest.raises(SnapshotError) as error:
        SourceRegister().require("paid-provider")
    assert error.value.code == "SOURCE_NOT_REGISTERED"


def test_snapshot_rejects_source_role_mismatch(tmp_path: Path):
    register = SourceRegister(
        (LegalSource("sec", SourceRole.FILING, "sec-terms", "indefinite"),)
    )
    with pytest.raises(SnapshotError) as error:
        SnapshotBuilder(
            FilesystemContentStore(tmp_path / "objects"),
            FilesystemSnapshotRepository(tmp_path / "manifests"),
            register,
        ).build(
            identity=identity(),
            valuation_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            captured_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            parser_version="fixture-parser-v1",
            policy_version="source-policy-v1",
            sources=(
                CapturedSource(
                    source_id="sec",
                    uri="https://example.test/10-k.html",
                    role=SourceRole.MACRO,
                    content=b"wrong role",
                    media_type="text/html",
                    http_status=200,
                    available_at=datetime(2025, 12, 1, tzinfo=timezone.utc),
                ),
            ),
        )
    assert error.value.code == "SOURCE_ROLE_MISMATCH"


def test_snapshot_rejects_naive_top_level_timestamps(tmp_path: Path):
    register = SourceRegister(
        (LegalSource("sec", SourceRole.FILING, "sec-terms", "indefinite"),)
    )
    with pytest.raises(SnapshotError) as error:
        SnapshotBuilder(
            FilesystemContentStore(tmp_path / "objects"),
            FilesystemSnapshotRepository(tmp_path / "manifests"),
            register,
        ).build(
            identity=identity(),
            valuation_timestamp=datetime(2026, 1, 1),
            captured_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            parser_version="fixture-parser-v1",
            policy_version="source-policy-v1",
            sources=(
                CapturedSource(
                    source_id="sec",
                    uri="https://example.test/10-k.html",
                    role=SourceRole.FILING,
                    content=b"filing",
                    media_type="text/html",
                    http_status=200,
                    available_at=datetime(2025, 12, 1, tzinfo=timezone.utc),
                    filed_at=datetime(2025, 12, 1, tzinfo=timezone.utc),
                    accession_number="0000000001-25-000001",
                    form="10-K",
                ),
            ),
        )
    assert error.value.code == "SNAPSHOT_TIMESTAMP_TIMEZONE_REQUIRED"


def test_snapshot_capture_time_covers_every_source_record(tmp_path: Path):
    register = SourceRegister(
        (LegalSource("sec", SourceRole.FILING, "sec-terms", "indefinite"),)
    )
    snapshot = SnapshotBuilder(
        FilesystemContentStore(tmp_path / "objects"),
        FilesystemSnapshotRepository(tmp_path / "manifests"),
        register,
    ).build(
        identity=identity(),
        valuation_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        captured_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        parser_version="fixture-parser-v1",
        policy_version="source-policy-v1",
        sources=(
            CapturedSource(
                source_id="sec",
                uri="https://example.test/10-k.html",
                role=SourceRole.FILING,
                content=b"captured later than the requested snapshot time",
                media_type="text/html",
                http_status=200,
                available_at=datetime(2025, 12, 1, tzinfo=timezone.utc),
                captured_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
                filed_at=datetime(2025, 12, 1, tzinfo=timezone.utc),
                accession_number="0000000001-25-000001",
                form="10-K",
            ),
        ),
    )

    assert snapshot.captured_at == datetime(2026, 1, 3, tzinfo=timezone.utc)
    assert all(
        record.captured_at <= snapshot.captured_at for record in snapshot.source_records
    )


def test_acquisition_metadata_does_not_change_point_in_time_coverage(
    tmp_path: Path,
):
    register = SourceRegister(
        (
            LegalSource("sec", SourceRole.FILING, "sec-terms", "indefinite"),
            LegalSource(
                "sec-submissions", SourceRole.REFERENCE, "sec-terms", "indefinite"
            ),
        )
    )
    snapshot = SnapshotBuilder(
        FilesystemContentStore(tmp_path / "objects"),
        FilesystemSnapshotRepository(tmp_path / "manifests"),
        register,
    ).build(
        identity=identity(),
        valuation_timestamp=datetime(2025, 6, 30, tzinfo=timezone.utc),
        captured_at=datetime(2026, 11, 6, tzinfo=timezone.utc),
        parser_version="fixture-parser-v1",
        policy_version="source-policy-v1",
        sources=(
            CapturedSource(
                source_id="sec",
                uri="https://example.test/10-k.html",
                role=SourceRole.FILING,
                content=b"filing available by cutoff",
                media_type="text/html",
                http_status=200,
                available_at=datetime(2024, 7, 30, tzinfo=timezone.utc),
                captured_at=datetime(2026, 11, 6, tzinfo=timezone.utc),
                accession_number="0000000001-24-000001",
                form="10-K",
                filed_at=datetime(2024, 7, 30, tzinfo=timezone.utc),
            ),
            CapturedSource(
                source_id="sec-submissions",
                uri="https://data.sec.gov/submissions/CIK0000000001.json",
                role=SourceRole.REFERENCE,
                content=b"current submissions index",
                media_type="application/json",
                http_status=200,
                available_at=datetime(2026, 11, 6, tzinfo=timezone.utc),
                captured_at=datetime(2026, 11, 6, tzinfo=timezone.utc),
                point_in_time_relevant=False,
            ),
        ),
    )

    assert snapshot.coverage_status.value == "verified"
    assert {record.source_id for record in snapshot.source_records} == {
        "sec",
        "sec-submissions",
    }
    submissions = next(
        record
        for record in snapshot.source_records
        if record.source_id == "sec-submissions"
    )
    assert submissions.available_at == datetime(2026, 11, 6, tzinfo=timezone.utc)
    assert submissions.point_in_time_relevant is False
    assert {record.source_id for record in select_available_sources(snapshot)} == {
        "sec"
    }


def test_snapshot_manifest_is_readable_without_provider_access(tmp_path: Path):
    snapshot = build(tmp_path, datetime(2026, 1, 2, tzinfo=timezone.utc))
    client = TestClient(
        create_app(FilesystemSnapshotRepository(tmp_path / "manifests"))
    )
    response = client.request(
        "GET",
        f"/v1/data/snapshots/{snapshot.snapshot_id}",
        headers=auth_headers(),
        json=make_internal_envelope({}),
    )
    assert response.status_code == 200
    assert response.json()["result"]["snapshot_id"] == snapshot.snapshot_id


def test_content_store_rejects_untrusted_hash_path(tmp_path: Path):
    store = FilesystemContentStore(tmp_path / "objects")
    with pytest.raises(SnapshotError) as error:
        store.get("../escape", media_type="text/plain")
    assert error.value.code == "SOURCE_HASH_INVALID"
