import asyncio
import hashlib
import json

import asyncpg
import pytest

import fundamental_service.persistence_recovery as recovery
from fundamental_service.metadata import (
    PostgresArtifactStore,
    PostgresContentStore,
    PostgresMetadataStore,
    PostgresSnapshotRepository,
)
from fundamental_service.persistence_recovery import (
    PersistenceBackupV1,
    RecoveryError,
    export_backup,
    main,
    restore_backup,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.contracts import CandidateRejectionV1
from fundamental_service.history_composition import verify_history_components
from test_history_composition import _changed, _compose, _original
from test_postgres_metadata import _fact_for_snapshot, _snapshot


def _seed(database_url, root, *, selected_view=False):
    store = PostgresMetadataStore(database_url, auto_migrate=True)
    store.start()
    content = PostgresContentStore(root, store)
    raw = b'{"original":"SEC fixture source"}'
    source_hash = content.put(raw, media_type="application/json")
    snapshot = _snapshot("recovery")
    payload = snapshot.model_dump(exclude={"manifest_digest"})
    payload["source_records"] = tuple(
        item.model_copy(update={"content_hash": source_hash})
        for item in snapshot.source_records
    )
    payload["manifest_digest"] = sha256_digest(
        {key: value for key, value in payload.items() if key != "snapshot_id"}
    )
    snapshot = type(snapshot)(**payload)
    store.publish_snapshot(snapshot)
    fact = _fact_for_snapshot(snapshot, "fact-recovery")
    fact = fact.model_copy(
        update={"source": fact.source.model_copy(update={"content_hash": source_hash})}
    )
    if selected_view:
        fact = fact.model_copy(
            update={
                "point_in_time_policy": "sec-public-pit-v1",
                "selection_reason": "original observation selected for the requested instant",
                "rejected_candidate_reasons": (
                    CandidateRejectionV1(
                        candidate_id="later-original",
                        reason="A later original was unavailable at this instant",
                    ),
                ),
            }
        )
    store.publish_fact(fact)
    store.publish_source_audit(
        acquisition_key="a" * 64,
        caller_principal="operator\\name\n測試",
        organization_id="test",
        correlation_id="recovery",
        source_hashes=(source_hash,),
        outcome="retained\tparser failure",
    )
    artifacts = PostgresArtifactStore(store, content)
    artifact = artifacts.put_with_receipt(
        "valuation:recovery",
        {"value": "123.45", "quality": "provisional"},
        (source_hash,),
    )
    # Keep unregistered original bytes too: a crash may precede metadata publication.
    orphan = b"retained parser failure"
    digest = hashlib.sha256(orphan).hexdigest()
    path = root / digest[:2] / f"{digest}.bin"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(orphan)
    return store, snapshot, fact, artifact


def _inventory(root):
    return tuple(
        (path.relative_to(root).as_posix(), path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


def _export(database_url, source, backups):
    return asyncio.run(
        export_backup(database_url, source, backups, source_revision="1" * 40)
    )


def _restore(database_url, target, bundle, digest):
    return asyncio.run(
        restore_backup(database_url, target, bundle, manifest_digest=digest)
    )


@pytest.mark.parametrize("selected_view", [False, True])
def test_backup_restores_metadata_and_bytes_and_repeats_without_writes(
    recovery_databases, tmp_path, selected_view
):
    source_db, target_db = recovery_databases
    source = tmp_path / "source"
    store, snapshot, fact, artifact = _seed(
        source_db, source, selected_view=selected_view
    )
    store.close()
    backups, target = tmp_path / "backups", tmp_path / "restored"
    first = _export(source_db, source, backups)
    assert first.wrote
    bundle = backups / first.manifest_digest
    before = _inventory(backups)
    assert _export(source_db, source, backups) == first.model_copy(
        update={"wrote": False}
    )
    assert _inventory(backups) == before
    restored = _restore(target_db, target, bundle, first.manifest_digest)
    assert restored == first
    target_before = _inventory(target)
    assert _restore(target_db, target, bundle, first.manifest_digest).wrote is False
    assert _inventory(target) == target_before
    reopened = PostgresMetadataStore(target_db)
    reopened.start()
    try:
        assert reopened.get_snapshot(snapshot.snapshot_id) == snapshot
        assert reopened.get_fact(fact.fact_id) == fact
        artifacts = PostgresArtifactStore(
            reopened, PostgresContentStore(target, reopened)
        )
        assert artifacts.get(artifact.artifact.artifact_id) == artifact.artifact
        assert artifacts.read(artifact.artifact.artifact_id) == canonical_bytes(
            {"value": "123.45", "quality": "provisional"}
        )
        assert (
            artifacts.put_with_receipt(
                artifact.artifact.artifact_id,
                {"value": "123.45", "quality": "provisional"},
                artifact.artifact.dependency_hashes,
            ).wrote
            is False
        )
    finally:
        reopened.close()
    assert _export(target_db, target, backups).wrote is False
    assert _inventory(backups) == before


@pytest.mark.parametrize("damage", [None, "missing", "changed"])
def test_history_backup_requires_each_original_and_recovers_same_composition(
    recovery_databases, tmp_path, damage
):
    source_db, target_db = recovery_databases
    source = tmp_path / "source"
    store = PostgresMetadataStore(source_db, auto_migrate=True)
    store.start()
    try:
        content = PostgresContentStore(source, store)
        repository = PostgresSnapshotRepository(store)
        originals = tuple(_original(year) for year in (2023, 2025))
        for year, original in zip((2023, 2025), originals, strict=True):
            assert (
                content.put(
                    canonical_bytes({"synthetic_original": year}),
                    media_type=original.source_records[0].media_type,
                )
                == original.source_records[0].content_hash
            )
            assert (
                content.put(
                    canonical_bytes({"synthetic_archive": year}),
                    media_type=original.source_records[1].media_type,
                )
                == original.source_records[1].content_hash
            )
        # Compose separately so a deliberately incomplete store can be tested.
        from fundamental_service.snapshots import FilesystemSnapshotRepository

        staging = FilesystemSnapshotRepository(tmp_path / "components")
        for original in originals:
            staging.publish(original)
        history = _compose(staging, originals)
        for index, original in enumerate(originals):
            if index == 0 and damage == "missing":
                continue
            if index == 0 and damage == "changed":
                original = _changed(original, policy_version="tampered")
            repository.publish(original)
        repository.publish(history)
    finally:
        store.close()
    backups = tmp_path / "backups"
    if damage is not None:
        with pytest.raises(RecoveryError, match="retained original"):
            _export(source_db, source, backups)
        assert list(backups.iterdir()) == []
        return
    receipt = _export(source_db, source, backups)
    before = _inventory(backups)
    assert _export(source_db, source, backups).wrote is False
    assert _inventory(backups) == before
    target = tmp_path / "target"
    _restore(
        target_db, target, backups / receipt.manifest_digest, receipt.manifest_digest
    )
    reopened = PostgresMetadataStore(target_db)
    reopened.start()
    try:
        restored = PostgresSnapshotRepository(reopened)
        assert (
            verify_history_components(restored.get(history.snapshot_id), restored)
            == originals
        )
        assert _compose(restored, originals) == history
        assert len(reopened.list_snapshots()) == 3
    finally:
        reopened.close()
    assert _export(target_db, target, backups).wrote is False


@pytest.mark.parametrize("damage", ["content", "table", "manifest", "extra", "symlink"])
def test_damaged_backup_is_rejected_before_target_mutation(
    recovery_databases, tmp_path, damage
):
    source_db, target_db = recovery_databases
    source = tmp_path / "source"
    store, _, _, _ = _seed(source_db, source)
    store.close()
    receipt = _export(source_db, source, tmp_path / "backups")
    bundle = tmp_path / "backups" / receipt.manifest_digest
    manifest = PersistenceBackupV1.model_validate_json(
        (bundle / "manifest.json").read_bytes()
    )
    if damage in {"content", "table"}:
        item = manifest.objects[0] if damage == "content" else manifest.tables[0].file
        (bundle / item.path).write_bytes(b"corrupt")
    elif damage == "manifest":
        (bundle / "manifest.json").write_bytes(b"{}")
    elif damage == "extra":
        (bundle / "undeclared.txt").write_bytes(b"extra")
    else:
        path = bundle / manifest.objects[0].path
        path.unlink()
        path.symlink_to(source / manifest.objects[0].path.removeprefix("content/"))
    target = tmp_path / "target"
    with pytest.raises((RecoveryError, ValueError)):
        _restore(target_db, target, bundle, receipt.manifest_digest)
    assert not target.exists()


def test_conflicting_target_is_preserved(recovery_databases, tmp_path):
    source_db, target_db = recovery_databases
    store, _, _, _ = _seed(source_db, tmp_path / "source")
    store.close()
    receipt = _export(source_db, tmp_path / "source", tmp_path / "backups")
    target = tmp_path / "target"
    other, _, _, _ = _seed(target_db, target)
    try:
        PostgresArtifactStore(other, PostgresContentStore(target, other)).put(
            "unrelated", {"retained": True}
        )
    finally:
        other.close()
    before = _inventory(target)
    with pytest.raises(RecoveryError, match="empty or identical"):
        _restore(
            target_db,
            target,
            tmp_path / "backups" / receipt.manifest_digest,
            receipt.manifest_digest,
        )
    assert _inventory(target) == before


def test_export_rejects_damaged_source_without_publishing(recovery_databases, tmp_path):
    source_db, _ = recovery_databases
    root = tmp_path / "source"
    store, _, _, _ = _seed(source_db, root)
    store.close()
    next(path for path in root.rglob("*") if path.is_file()).write_bytes(b"damaged")
    backups = tmp_path / "backups"
    with pytest.raises(RecoveryError, match="digest verification"):
        _export(source_db, root, backups)
    assert list(backups.iterdir()) == []


def test_interrupted_restore_rolls_back_and_retries_from_retained_bytes(
    recovery_databases, tmp_path, monkeypatch
):
    source_db, target_db = recovery_databases
    source = tmp_path / "source"
    store, _, _, artifact = _seed(source_db, source)
    store.close()
    receipt = _export(source_db, source, tmp_path / "backups")
    bundle = tmp_path / "backups" / receipt.manifest_digest
    original = recovery._copy_rows

    async def interrupted(root, table):
        async for chunk in original(root, table):
            yield chunk
            raise RecoveryError("injected restore interruption")

    target = tmp_path / "target"
    with monkeypatch.context() as patch:
        patch.setattr(recovery, "_copy_rows", interrupted)
        with pytest.raises(RecoveryError, match="interruption"):
            _restore(target_db, target, bundle, receipt.manifest_digest)
    before = _inventory(target)
    assert before
    # A process killed before linking a file can leave only uncommitted staging bytes.
    pending = target / ".restore-pending" / "interrupted-copy"
    pending.parent.mkdir(exist_ok=True)
    pending.write_bytes(b"incomplete")
    before = _inventory(target)
    assert _restore(target_db, target, bundle, receipt.manifest_digest).wrote
    assert _inventory(target) == before
    assert _export(target_db, target, tmp_path / "backups").wrote is False
    reopened = PostgresMetadataStore(target_db)
    reopened.start()
    try:
        assert reopened.get_artifact(artifact.artifact.artifact_id) == artifact.artifact
        reopened.publish_source_audit(
            acquisition_key="b" * 64,
            caller_principal="operator",
            organization_id="test",
            correlation_id="after-restore",
            source_hashes=(),
            outcome="restarted",
        )
    finally:
        reopened.close()

    async def check_audits():
        connection = await asyncpg.connect(target_db)
        try:
            rows = await connection.fetch(
                "SELECT audit_id, caller_principal, outcome FROM fundamental.source_acquisition_audits ORDER BY audit_id"
            )
            assert [row["audit_id"] for row in rows] == [1, 2]
            assert rows[0]["caller_principal"] == "operator\\name\n測試"
            assert rows[0]["outcome"] == "retained\tparser failure"
        finally:
            await connection.close()

    asyncio.run(check_audits())


def test_backup_missing_referenced_source_is_not_published(
    recovery_databases, tmp_path
):
    source_db, _ = recovery_databases
    source = tmp_path / "source"
    store, snapshot, _, _ = _seed(source_db, source)
    source_hash = snapshot.source_records[0].content_hash
    source_file = source / source_hash[:2] / f"{source_hash}.json"

    # Missing raw evidence must not be hidden by removing its registry entry.
    async def remove_registration():
        connection = await asyncpg.connect(source_db)
        try:
            await connection.execute(
                "DELETE FROM fundamental.content_objects WHERE content_hash=$1",
                source_hash,
            )
        finally:
            await connection.close()

    store.close()
    asyncio.run(remove_registration())
    source_file.unlink()
    backups = tmp_path / "backups"
    with pytest.raises(RecoveryError, match="absent from backup"):
        _export(source_db, source, backups)
    assert list(backups.iterdir()) == []


def test_command_does_not_print_credentials(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(
        "FUNDAMENTAL_SERVICE_DATABASE_URL", "invalid-secret-database-url"
    )
    monkeypatch.setenv("FUNDAMENTAL_SERVICE_DATA_ROOT", str(tmp_path))
    assert (
        main(
            [
                "export",
                "--destination",
                str(tmp_path / "backups"),
                "--source-revision",
                "1" * 40,
            ]
        )
        == 2
    )
    assert "secret" not in capsys.readouterr().err


def test_manifest_rejects_path_traversal():
    with pytest.raises(ValueError, match="match its digest"):
        PersistenceBackupV1.model_validate_json(
            json.dumps(
                {
                    "source_revision": "1" * 40,
                    "migration_digest": "a" * 64,
                    "schema_digest": "b" * 64,
                    "postgres_major": 16,
                    "tables": [
                        {
                            "name": "snapshots",
                            "columns": ["id"],
                            "row_count": 0,
                            "file": {
                                "path": "tables/snapshots.jsonl",
                                "digest": "c" * 64,
                                "byte_length": 0,
                            },
                        }
                    ],
                    "objects": [
                        {
                            "path": "content/../../escape",
                            "digest": "d" * 64,
                            "byte_length": 1,
                        }
                    ],
                }
            )
        )
