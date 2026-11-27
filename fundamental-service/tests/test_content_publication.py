import os
import stat
import asyncio
import hashlib
from pathlib import Path

import pytest

from fundamental_service.content_publication import (
    PrivateContentPublication,
    TrustedReaderGroupPublication,
    configured_content_publication_access,
)
from fundamental_service.snapshots import FilesystemContentStore, SnapshotError
from fundamental_service.metadata import (
    PostgresArtifactStore,
    PostgresContentStore,
    PostgresMetadataStore,
)


def _group():
    return TrustedReaderGroupPublication(os.getegid())


def test_private_default_keeps_owner_only_bytes_and_ignores_environment(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("FUNDAMENTAL_SERVICE_CONTENT_READER_GID", "invalid")
    store = FilesystemContentStore(tmp_path / "content")
    digest = store.put(b"private", media_type="application/json")
    path = store._path(digest, "application/json")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert store.get(digest, media_type="application/json") == b"private"


def test_group_publication_survives_private_umask_and_reuses_without_mutation(
    tmp_path, monkeypatch
):
    previous = os.umask(0o077)
    try:
        store = FilesystemContentStore(
            tmp_path / "content", publication_access=_group()
        )
        digest = store.put(b"shared", media_type="application/json")
    finally:
        os.umask(previous)
    path = store._path(digest, "application/json")
    for directory in (store.root, path.parent):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o750
        assert directory.stat().st_gid == os.getegid()
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert path.stat().st_gid == os.getegid()
    before = path.stat()

    def forbidden(*args, **kwargs):
        pytest.fail("reuse must not change permissions")

    monkeypatch.setattr(os, "fchmod", forbidden)
    monkeypatch.setattr(os, "fchown", forbidden)
    monkeypatch.setattr(os, "chmod", forbidden)
    monkeypatch.setattr(os, "chown", forbidden)
    assert store.put(b"shared", media_type="application/json") == digest
    assert store.get(digest, media_type="application/json") == b"shared"
    assert path.stat() == before


@pytest.mark.parametrize("value", ["", "0", "-1", "abc", " 20", "4294967295"])
def test_invalid_deployment_group_is_named_refusal(monkeypatch, value):
    monkeypatch.setenv("FUNDAMENTAL_SERVICE_CONTENT_READER_GID", value)
    with pytest.raises(SnapshotError) as error:
        configured_content_publication_access()
    assert error.value.code == "CONTENT_PUBLICATION_ACCESS_UNAVAILABLE"


def test_loader_requires_publisher_membership_and_defaults_private(monkeypatch):
    monkeypatch.delenv("FUNDAMENTAL_SERVICE_CONTENT_READER_GID", raising=False)
    assert configured_content_publication_access() == PrivateContentPublication()
    monkeypatch.setenv("FUNDAMENTAL_SERVICE_CONTENT_READER_GID", str(os.getegid()))
    assert configured_content_publication_access() == _group()
    monkeypatch.setenv("FUNDAMENTAL_SERVICE_CONTENT_READER_GID", "123456")
    monkeypatch.setattr(os, "getgroups", lambda: [])
    monkeypatch.setattr(os, "getegid", lambda: 20)
    with pytest.raises(SnapshotError) as error:
        configured_content_publication_access()
    assert error.value.code == "CONTENT_PUBLICATION_ACCESS_UNAVAILABLE"


@pytest.mark.parametrize("operation", ["fchown", "fchmod"])
def test_failed_access_preparation_publishes_no_object(
    tmp_path, monkeypatch, operation
):
    store = FilesystemContentStore(tmp_path / "content", publication_access=_group())

    def denied(*args, **kwargs):
        raise PermissionError("injected access setup failure")

    monkeypatch.setattr(os, operation, denied)
    with pytest.raises(SnapshotError) as error:
        store.put(b"shared", media_type="application/json")
    assert error.value.code == "CONTENT_PUBLICATION_ACCESS_UNAVAILABLE"
    assert tuple(store.root.rglob("*.json")) == ()
    assert tuple(store.root.rglob("snapshot-*")) == ()


def test_existing_private_object_requires_install_and_is_never_repaired(tmp_path):
    store = FilesystemContentStore(tmp_path / "content", publication_access=_group())
    digest = store.put(b"shared", media_type="application/json")
    path = store._path(digest, "application/json")
    path.chmod(0o600)
    before = path.stat()
    for operation in (
        lambda: store.get(digest, media_type="application/json"),
        lambda: store.put(b"shared", media_type="application/json"),
    ):
        with pytest.raises(SnapshotError) as error:
            operation()
        assert error.value.code == "CONTENT_ACCESS_INSTALL_REQUIRED"
        assert path.stat() == before


def test_existing_private_directory_requires_install(tmp_path):
    root = tmp_path / "content"
    root.mkdir(mode=0o700)
    before = root.stat()
    with pytest.raises(SnapshotError) as error:
        FilesystemContentStore(root, publication_access=_group())
    assert error.value.code == "CONTENT_ACCESS_INSTALL_REQUIRED"
    assert root.stat() == before


def test_permission_error_is_storage_refusal_and_corruption_still_fails(
    tmp_path, monkeypatch
):
    store = FilesystemContentStore(tmp_path / "content", publication_access=_group())
    digest = store.put(b"shared", media_type="application/json")
    path = store._path(digest, "application/json")
    path.write_bytes(b"tampered")
    with pytest.raises(SnapshotError) as error:
        store.get(digest, media_type="application/json")
    assert error.value.code == "SOURCE_HASH_MISMATCH"

    def denied(self):
        raise PermissionError("injected inaccessible content")

    monkeypatch.setattr(Path, "read_bytes", denied)
    with pytest.raises(SnapshotError) as error:
        store.get(digest, media_type="application/json")
    assert error.value.code == "SOURCE_BYTES_FORBIDDEN"


def test_readonly_content_never_creates_repairs_or_registers(tmp_path, monkeypatch):
    from unittest.mock import Mock

    metadata = Mock(spec=PostgresMetadataStore)
    writable = PostgresContentStore(
        tmp_path / "content", metadata, publication_access=_group()
    )
    digest = writable.put(b"shared", media_type="application/json")
    metadata.reset_mock()
    metadata.content_byte_length.return_value = len(b"shared")

    def forbidden(*args, **kwargs):
        pytest.fail("readonly access must not mutate storage")

    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr(os, "chmod", forbidden)
    monkeypatch.setattr(os, "chown", forbidden)
    monkeypatch.setattr(os, "fchmod", forbidden)
    monkeypatch.setattr(os, "fchown", forbidden)
    for reader in (
        writable.as_read_only(),
        PostgresContentStore(tmp_path / "content", metadata, read_only=True),
    ):
        assert reader.get(digest, media_type="application/json") == b"shared"
        with pytest.raises(SnapshotError) as error:
            reader.put(b"not allowed", media_type="application/json")
        assert error.value.code == "READ_ONLY_STORAGE"
    metadata.register_content.assert_not_called()
    metadata.content_byte_length.return_value = None
    with pytest.raises(SnapshotError) as error:
        writable.as_read_only().get(digest, media_type="application/json")
    assert error.value.code == "CONTENT_METADATA_MISMATCH"


def test_failed_publication_does_not_register_metadata(tmp_path, monkeypatch):
    from unittest.mock import Mock

    metadata = Mock(spec=PostgresMetadataStore)
    content = PostgresContentStore(
        tmp_path / "content", metadata, publication_access=_group()
    )

    def denied(*args, **kwargs):
        raise PermissionError("injected FD access failure")

    monkeypatch.setattr(os, "fchmod", denied)
    with pytest.raises(SnapshotError) as error:
        content.put(b"shared", media_type="application/json")
    assert error.value.code == "CONTENT_PUBLICATION_ACCESS_UNAVAILABLE"
    metadata.register_content.assert_not_called()
    assert tuple((tmp_path / "content").rglob("*.json")) == ()


def test_artifact_duplicate_checks_access_before_early_return(
    recovery_databases, tmp_path
):
    metadata = PostgresMetadataStore(recovery_databases[0], auto_migrate=True)
    metadata.start()
    try:
        content = PostgresContentStore(
            tmp_path / "content", metadata, publication_access=_group()
        )
        artifacts = PostgresArtifactStore(metadata, content)
        first = artifacts.put_with_receipt("access-test", {"retained": "bytes"})
        path = content._filesystem._path(
            first.artifact.content_hash, first.artifact.media_type
        )
        before = path.stat()
        assert (
            artifacts.put_with_receipt("access-test", {"retained": "bytes"}).wrote
            is False
        )
        assert path.stat() == before
        path.chmod(0o600)
        before = path.stat()
        with pytest.raises(SnapshotError) as error:
            artifacts.put_with_receipt("access-test", {"retained": "bytes"})
        assert error.value.code == "CONTENT_ACCESS_INSTALL_REQUIRED"
        assert path.stat() == before
    finally:
        metadata.close()


def test_bounded_backup_restore_publishes_group_access_and_retry_checks_existing(
    recovery_databases, tmp_path
):
    from fundamental_service.persistence_recovery import export_backup
    from recovery_test_support import restore_backup

    source_db, target_db = recovery_databases
    metadata = PostgresMetadataStore(source_db, auto_migrate=True)
    metadata.start()
    source = tmp_path / "source"
    try:
        content = PostgresContentStore(source, metadata)
        digest = content.put(b"retained backup bytes", media_type="application/json")
    finally:
        metadata.close()
    exported = asyncio.run(
        export_backup(source_db, source, tmp_path / "backups", source_revision="1" * 40)
    )
    target = tmp_path / "restored"
    bundle = tmp_path / "backups" / exported.manifest_digest

    def restore():
        return asyncio.run(
            restore_backup(
                target_db,
                target,
                bundle,
                manifest_digest=exported.manifest_digest,
                publication_access=_group(),
            )
        )

    assert restore().wrote is True
    path = target / digest[:2] / f"{digest}.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert path.stat().st_gid == os.getegid()
    assert stat.S_IMODE((target / ".restore-pending").stat().st_mode) == 0o700
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    before = path.stat()
    assert restore().wrote is False
    assert path.stat() == before
    path.chmod(0o600)
    before = path.stat()
    with pytest.raises(SnapshotError) as error:
        restore()
    assert error.value.code == "CONTENT_ACCESS_INSTALL_REQUIRED"
    assert path.stat() == before


@pytest.mark.parametrize("existing_private", [False, True])
def test_interrupted_group_restore_checks_access_before_retrying(
    recovery_databases, tmp_path, monkeypatch, existing_private
):
    import fundamental_service.persistence_recovery as recovery
    from recovery_test_support import restore_backup

    source_db, target_db = recovery_databases
    metadata = PostgresMetadataStore(source_db, auto_migrate=True)
    metadata.start()
    source = tmp_path / "source"
    try:
        content = PostgresContentStore(source, metadata)
        content.put(b"retained retry bytes", media_type="application/json")
    finally:
        metadata.close()
    exported = asyncio.run(
        recovery.export_backup(
            source_db, source, tmp_path / "backups", source_revision="1" * 40
        )
    )
    target = tmp_path / "restored"
    bundle = tmp_path / "backups" / exported.manifest_digest

    def restore():
        return asyncio.run(
            restore_backup(
                target_db,
                target,
                bundle,
                manifest_digest=exported.manifest_digest,
                publication_access=_group(),
            )
        )

    async def interrupted(*args, **kwargs):
        raise asyncio.CancelledError("injected cancellation after byte publication")

    with monkeypatch.context() as patch:
        patch.setattr(recovery, "_install_bundle", interrupted)
        with pytest.raises(asyncio.CancelledError):
            restore()
    before = tuple(
        (path, path.read_bytes(), path.stat()) for path in target.rglob("*.json")
    )
    assert before
    assert tuple((target / ".restore-pending").iterdir()) == ()
    if existing_private:
        path = before[0][0]
        path.chmod(0o600)
        private_stat = path.stat()
        with pytest.raises(SnapshotError) as error:
            restore()
        assert error.value.code == "CONTENT_ACCESS_INSTALL_REQUIRED"
        assert path.read_bytes() == before[0][1]
        after = path.stat()
        for field in (
            "st_mode",
            "st_ino",
            "st_dev",
            "st_nlink",
            "st_uid",
            "st_gid",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        ):
            assert getattr(after, field) == getattr(private_stat, field), field
        return
    assert restore().wrote is True
    assert (
        tuple((path, path.read_bytes(), path.stat()) for path, _, _ in before) == before
    )


def test_restore_cli_names_publication_refusal_without_disclosing_path(
    monkeypatch, capsys
):
    from fundamental_service.persistence_recovery import main

    monkeypatch.setenv("FUNDAMENTAL_SERVICE_DATABASE_URL", "unused")
    monkeypatch.setenv("FUNDAMENTAL_SERVICE_DATA_ROOT", "/private/content-root")
    monkeypatch.setenv("FUNDAMENTAL_SERVICE_CONTENT_READER_GID", "invalid")
    assert (
        main(
            [
                "restore",
                "--bundle",
                "/private/bundle",
                "--manifest-digest",
                "a" * 64,
                "--authorization",
                "/private/authorization",
            ]
        )
        == 2
    )
    output = capsys.readouterr()
    assert '"code":"CONTENT_PUBLICATION_ACCESS_UNAVAILABLE"' in output.err
    assert "/private" not in output.err
    assert output.out == ""
