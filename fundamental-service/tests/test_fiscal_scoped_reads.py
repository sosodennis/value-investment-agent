from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
import test_fiscal_admission_history as history_cases
from sqlalchemy import text

from fundamental_service.data_releases import DataReleaseError
from fundamental_service.metadata import PostgresArtifactStore, PostgresContentStore
from fundamental_service.snapshots import SnapshotError

metadata = history_cases.metadata
database_url = history_cases.database_url
artifacts = history_cases.artifacts


def test_scoped_read_is_readonly_nested_and_not_reused_outside_operation(
    metadata, artifacts, monkeypatch
):
    record = artifacts.put_with_receipt("scoped-one", {"value": "1"}).artifact
    readonly = artifacts.as_read_only()
    original = metadata.retained_artifact_records
    observed = []

    def counting(ids):
        observed.append(ids)
        return original(ids)

    monkeypatch.setattr(metadata, "retained_artifact_records", counting)
    with pytest.raises(SnapshotError, match="read-only"):
        with artifacts.scoped_read_operation():
            pass
    with readonly.scoped_read_operation():
        assert readonly.get(record.artifact_id) == record
        assert readonly.as_read_only().get(record.artifact_id) == record
        with readonly.scoped_read_operation():
            assert readonly.read(record.artifact_id) == b'{"value":"1"}'
        assert readonly.get(record.artifact_id) == record
        assert observed.count((record.artifact_id,)) == 1
        readonly.seal_scoped_read_operation()
        with pytest.raises(RuntimeError, match="ended"):
            readonly.get(record.artifact_id)
    assert readonly.get(record.artifact_id) == record
    assert readonly.read(record.artifact_id) == b'{"value":"1"}'


def test_scoped_final_mutation_corrupt_bytes_and_missing_registration_refuse(
    metadata, artifacts, tmp_path
):
    record = artifacts.put_with_receipt("scoped-one", {"value": "1"}).artifact
    readonly = artifacts.as_read_only()
    with pytest.raises(DataReleaseError, match="changed"):
        with readonly.scoped_read_operation():
            readonly.read(record.artifact_id)

            async def invalidate(connection):
                await connection.execute(
                    text(
                        "UPDATE fundamental.artifact_references SET status='invalidated' WHERE artifact_id=:identity"
                    ),
                    {"identity": record.artifact_id},
                )

            metadata.run_fiscal_admission_history(invalidate)
            readonly.seal_scoped_read_operation()
    current = readonly.get(record.artifact_id)
    assert current.status == "invalidated"
    another = artifacts.put_with_receipt("scoped-another", {"value": "2"}).artifact
    path = tmp_path / another.content_hash[:2] / (another.content_hash + ".json")
    path.write_bytes(b"corrupt")
    with pytest.raises(SnapshotError):
        with readonly.scoped_read_operation():
            readonly.read(another.artifact_id)
    missing = artifacts.put_with_receipt("scoped-unregistered", {"value": "3"}).artifact

    async def remove_registration(connection):
        await connection.execute(
            text("DELETE FROM fundamental.content_objects WHERE content_hash=:digest"),
            {"digest": missing.content_hash},
        )

    metadata.run_fiscal_admission_history(remove_registration)
    with pytest.raises(SnapshotError, match="cannot repair"):
        with readonly.scoped_read_operation():
            readonly.read(missing.artifact_id)
    with pytest.raises(SnapshotError, match="registration is missing"):
        metadata.content_byte_length(
            missing.content_hash, media_type=missing.media_type
        )


def test_scoped_reads_parallel_contexts_and_content_roots_are_isolated(
    metadata, artifacts, tmp_path
):
    record = artifacts.put_with_receipt("scoped-one", {"value": "1"}).artifact
    readonly = artifacts.as_read_only()
    other_root = tmp_path / "other-root"
    other_root.mkdir()
    other = PostgresArtifactStore(
        metadata,
        PostgresContentStore(other_root, metadata, read_only=True),
        read_only=True,
    )
    barrier = Barrier(2)

    def operation():
        with readonly.scoped_read_operation():
            assert readonly.read(record.artifact_id) == b'{"value":"1"}'
            barrier.wait(timeout=5)
            readonly.seal_scoped_read_operation()
        return readonly.get(record.artifact_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = pool.submit(operation), pool.submit(operation)
        assert one.result(timeout=10) == two.result(timeout=10) == record
    with readonly.scoped_read_operation():
        readonly.read(record.artifact_id)
        with pytest.raises(SnapshotError):
            other.read(record.artifact_id)
    with pytest.raises(RuntimeError, match="cancel"):
        with readonly.scoped_read_operation():
            readonly.get(record.artifact_id)
            raise RuntimeError("cancel")
    assert readonly.get(record.artifact_id) == record
