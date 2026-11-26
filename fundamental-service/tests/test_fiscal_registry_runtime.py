from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fundamental_service import fiscal_registry_runtime as registry_module
from fundamental_service.fiscal_authority_contracts import (
    FiscalGrantAuthorityCommandV1,
    FiscalRevokeAuthorityCommandV1,
    fiscal_authority_command_artifact_id,
)
from fundamental_service.fiscal_registry_runtime import (
    FiscalRegistryInstallationV1,
    FiscalRegistryOrderV1,
    FiscalRegistryRuntime,
    build_fiscal_registry_reader,
    fiscal_registry_executable_digest,
)
from fundamental_service.metadata import PostgresArtifactStore, PostgresContentStore
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
from test_fiscal_admission_authority import deadline

pytest_plugins = ("test_fiscal_admission_authority",)


@dataclass
class RegistryEnvironment:
    runtime: FiscalRegistryRuntime
    order: FiscalRegistryOrderV1
    installation: FiscalRegistryInstallationV1
    base: object

    def write(self, order: FiscalRegistryOrderV1) -> None:
        path = self.installation.orders_directory / (order.order_id + ".json")
        path.write_bytes(canonical_bytes(order))
        path.chmod(0o600)


@pytest.fixture
def artifacts(metadata, tmp_path):
    return PostgresArtifactStore(
        metadata, PostgresContentStore(tmp_path / "content", metadata)
    )


@pytest.fixture
def protected_registry_directory() -> Iterator[Path]:
    with TemporaryDirectory(
        prefix="fundamental-registry-test-", dir=Path.home()
    ) as root:
        yield Path(root)


@pytest.fixture
def registry(environment, protected_registry_directory):
    root = environment.configuration[0].roots[0].identity
    deployment = protected_registry_directory / "deployment.json"
    deployment.write_bytes(canonical_bytes(environment.configuration[0]))
    deployment.chmod(0o600)
    key = protected_registry_directory / "registry.pem"
    key.write_bytes(
        environment.signer.private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key.chmod(0o600)
    orders = protected_registry_directory / "orders"
    orders.mkdir(mode=0o700)
    installation = FiscalRegistryInstallationV1(
        audience="ephemeral-registry",
        root_id=root.root_id,
        workload_uid=os.getuid(),
        deployment_uid=os.getuid(),
        database_role="fundamental",
        deployment_file=deployment,
        orders_directory=orders,
        private_key_file=key,
        executable_digest=fiscal_registry_executable_digest(),
    )
    runtime = FiscalRegistryRuntime(
        installation=installation,
        artifacts=environment.store,
        metadata=environment.metadata,
    )
    now = datetime.now(UTC)
    order = FiscalRegistryOrderV1(
        order_id="grant-one",
        audience=installation.audience,
        root_id=root.root_id,
        deployment_digest=sha256_digest(environment.configuration[0]),
        executable_digest=installation.executable_digest,
        issuance=environment.history.read_epoch(
            deadline_at=deadline()
        ).issuance_context,
        command=FiscalGrantAuthorityCommandV1(
            command_id="registry-grant",
            authority_id="synthetic-classifier",
            expires_at=now + timedelta(hours=1),
        ),
        expected_head=None,
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(minutes=10),
    )
    result = RegistryEnvironment(runtime, order, installation, environment)
    result.write(order)
    return result


def test_protected_order_grant_current_duplicate_revoke(registry):
    first = registry.runtime.apply(registry.order.order_id, deadline_at=deadline())
    again = registry.runtime.apply(registry.order.order_id, deadline_at=deadline())
    assert first.signed_record == again.signed_record
    assert first.publication.wrote and not again.publication.wrote
    reader = build_fiscal_registry_reader(
        deployment_file=registry.installation.deployment_file,
        deployment_uid=os.getuid(),
        artifacts=registry.base.store,
        metadata=registry.base.metadata,
    )
    current = reader.read_current(
        "synthetic-classifier", expected_role="classifier", deadline_at=deadline()
    )
    assert current.grant_ref.artifact_id == first.signed_record.artifact_id
    command = FiscalRevokeAuthorityCommandV1(
        command_id="registry-revoke",
        authority_id="synthetic-classifier",
        grant_ref=current.grant_ref,
        reason="ephemeral revocation",
    )
    order = registry.order.model_copy(
        update={
            "order_id": "revoke-one",
            "command": command,
            "expected_head": next(
                h for h in current.history_heads if h.stream_kind == "control"
            ),
        }
    )
    registry.write(order)
    revoked = registry.runtime.apply(order.order_id, deadline_at=deadline())
    assert revoked.signed_record.record.command == command
    with pytest.raises(SnapshotError, match="revoked"):
        reader.read_current(
            "synthetic-classifier", expected_role="classifier", deadline_at=deadline()
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("audience", "wrong"),
        ("root_id", "wrong"),
        ("deployment_digest", "f" * 64),
        ("executable_digest", "f" * 64),
        ("valid_from", datetime.now(UTC) + timedelta(days=1)),
        ("valid_until", datetime.now(UTC) - timedelta(days=1)),
    ],
)
def test_protected_order_binding_refuses_before_signing(registry, field, value):
    changed = registry.order.model_copy(update={field: value})
    registry.write(changed)
    with pytest.raises(SnapshotError):
        registry.runtime.apply(changed.order_id, deadline_at=deadline())
    with pytest.raises(SnapshotError) as unavailable:
        registry.base.store.get(fiscal_authority_command_artifact_id(changed.command))
    assert unavailable.value.code == "ARTIFACT_NOT_FOUND"
    assert registry.base.signer.sign_calls == 0


@pytest.mark.parametrize(
    "unsafe",
    [
        "key-mode",
        "key-type",
        "key-mismatch",
        "order-symlink",
        "parent-mode",
        "order-fifo",
    ],
)
def test_custody_rejects_unsafe_objects_without_authority(registry, unsafe):
    order_path = registry.installation.orders_directory / (
        registry.order.order_id + ".json"
    )
    if unsafe == "key-mode":
        registry.installation.private_key_file.chmod(0o644)
    elif unsafe == "key-type":
        registry.installation.private_key_file.write_bytes(b"not a key")
    elif unsafe == "key-mismatch":
        registry.installation.private_key_file.write_bytes(
            Ed25519PrivateKey.generate().private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
    elif unsafe == "order-symlink":
        target = order_path.with_suffix(".original")
        order_path.rename(target)
        order_path.symlink_to(target)
    elif unsafe == "order-fifo":
        order_path.unlink()
        os.mkfifo(order_path)
    else:
        registry.installation.orders_directory.chmod(0o777)
    try:
        with pytest.raises(SnapshotError):
            registry.runtime.apply(registry.order.order_id, deadline_at=deadline())
        with pytest.raises(SnapshotError):
            registry.base.store.get(
                fiscal_authority_command_artifact_id(registry.order.command)
            )
    finally:
        registry.installation.orders_directory.chmod(0o700)


def test_signed_outcome_recovers_exact_bytes_without_signing_again(
    registry, monkeypatch
):
    original = registry.base.store.put_bytes_with_receipt
    native_sign = registry_module._RegistryJob.sign
    calls = []

    def sign(self, *args, **kwargs):
        calls.append(1)
        return native_sign(self, *args, **kwargs)

    def crash(artifact_id, *args, **kwargs):
        if artifact_id == fiscal_authority_command_artifact_id(registry.order.command):
            raise RuntimeError("cut after exact outcome, before authority registration")
        return original(artifact_id, *args, **kwargs)

    monkeypatch.setattr(registry_module._RegistryJob, "sign", sign)
    monkeypatch.setattr(registry.base.store, "put_bytes_with_receipt", crash)
    with pytest.raises(RuntimeError, match="cut after exact outcome"):
        registry.runtime.apply(registry.order.order_id, deadline_at=deadline())
    key = sha256_digest(
        (
            "fiscal-registry",
            fiscal_authority_command_artifact_id(registry.order.command),
        )
    )
    signed_raw = registry.base.store.read("fiscal-registry-job-v1:" + key + ":signed")
    monkeypatch.setattr(registry.base.store, "put_bytes_with_receipt", original)
    recovered = registry.runtime.apply(registry.order.order_id, deadline_at=deadline())
    assert canonical_bytes(recovered.signed_record) == signed_raw
    assert registry.base.store.read(recovered.signed_record.artifact_id) == signed_raw
    assert len(calls) == 1


def test_unknown_sign_outcome_refuses_same_job(registry, monkeypatch):
    original = registry.base.store.put_bytes_with_receipt
    calls = []

    def crash(artifact_id, *args, **kwargs):
        if artifact_id.endswith(":signed"):
            calls.append(1)
            raise RuntimeError("cut after private signature, before durable outcome")
        return original(artifact_id, *args, **kwargs)

    monkeypatch.setattr(registry.base.store, "put_bytes_with_receipt", crash)
    with pytest.raises(RuntimeError, match="cut after private signature"):
        registry.runtime.apply(registry.order.order_id, deadline_at=deadline())
    monkeypatch.setattr(registry.base.store, "put_bytes_with_receipt", original)
    with pytest.raises(SnapshotError) as failure:
        registry.runtime.apply(registry.order.order_id, deadline_at=deadline())
    assert failure.value.code == "FISCAL_REGISTRY_SIGNING_OUTCOME_UNAVAILABLE"
    assert len(calls) == 1


def test_lease_exact_identity_and_lost_connection_refuse(metadata):
    from dataclasses import replace

    lease = metadata.try_acquire_ingestion_lock("a" * 64)
    assert lease is not None
    assert metadata.require_ingestion_lock(lease).utcoffset() is not None
    with pytest.raises(SnapshotError):
        metadata.require_ingestion_lock(
            replace(lease, advisory_key=lease.advisory_key + 1)
        )
    metadata.release_ingestion_lock(lease)
    with pytest.raises(SnapshotError) as failure:
        metadata.require_ingestion_lock(lease)
    assert failure.value.code == "INGESTION_LOCK_LOST"


def test_expired_deadline_does_not_create_job(registry):
    with pytest.raises(SnapshotError) as failure:
        registry.runtime.apply(
            registry.order.order_id,
            deadline_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    assert failure.value.code == "REQUEST_DEADLINE_EXCEEDED"


def test_order_unknown_and_traversal_refused(registry):
    for identity in ("absent", "../grant-one", "/etc/passwd"):
        with pytest.raises(SnapshotError):
            registry.runtime.apply(identity, deadline_at=deadline())


def test_reader_select_only_without_key_and_without_registration_repair(
    registry, tmp_path, monkeypatch, database_url
):
    from fundamental_service.metadata import (
        PostgresArtifactStore,
        PostgresContentStore,
        PostgresMetadataStore,
    )
    from test_fiscal_candidate_read_runtime import select_only_role
    from sqlalchemy import text

    publication = registry.runtime.apply(
        registry.order.order_id, deadline_at=deadline()
    )
    registry.installation.private_key_file.unlink()
    with select_only_role(registry.base.metadata, database_url) as reader_url:
        metadata = PostgresMetadataStore(reader_url, auto_migrate=False)

        def forbid(*args, **kwargs):
            raise AssertionError("reader attempted publication or repair")

        monkeypatch.setattr(metadata, "register_content", forbid)
        monkeypatch.setattr(metadata, "publish_artifact", forbid)
        monkeypatch.setattr(metadata, "_apply_migration", forbid)
        try:
            metadata.start_read_only()
            store = PostgresArtifactStore(
                metadata,
                PostgresContentStore(tmp_path / "content", metadata, read_only=True),
                read_only=True,
            )
            reader = build_fiscal_registry_reader(
                deployment_file=registry.installation.deployment_file,
                deployment_uid=os.getuid(),
                artifacts=store,
                metadata=metadata,
            )
            current = reader.read_current(
                "synthetic-classifier",
                expected_role="classifier",
                deadline_at=deadline(),
            )
            assert (
                current.grant_ref.artifact_id == publication.signed_record.artifact_id
            )

            async def privileges(connection):
                return tuple(
                    (
                        await connection.execute(
                            text(
                                "SELECT has_table_privilege(current_user,'fundamental.artifact_references','INSERT'), has_schema_privilege(current_user,'fundamental','CREATE')"
                            )
                        )
                    ).one()
                )

            assert metadata.run_fiscal_admission_history(privileges) == (False, False)
        finally:
            metadata.close()


@pytest.mark.parametrize("cut", ["checkpoint", "append", "seal"])
def test_owner_durable_cuts_resume_original_signature(registry, monkeypatch, cut):
    from fundamental_service.fiscal_admission_history import (
        PostgresFiscalAdmissionHistory,
    )

    method = {
        "checkpoint": "checkpoint",
        "append": "append_once",
        "seal": "seal_pending",
    }[cut]
    original = getattr(PostgresFiscalAdmissionHistory, method)
    tripped = []

    def crash(self, *args, **kwargs):
        if not tripped and (cut != "seal" or args[0][0].startswith("control:")):
            tripped.append(1)
            if cut == "append":
                original(self, *args, **kwargs)
            raise RuntimeError("durable owner cut " + cut)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(PostgresFiscalAdmissionHistory, method, crash)
    with pytest.raises(RuntimeError, match="durable owner cut"):
        registry.runtime.apply(registry.order.order_id, deadline_at=deadline())
    monkeypatch.setattr(PostgresFiscalAdmissionHistory, method, original)
    artifact_id = fiscal_authority_command_artifact_id(registry.order.command)
    raw = registry.base.store.read(artifact_id)
    recovered = registry.runtime.apply(registry.order.order_id, deadline_at=deadline())
    assert (
        registry.base.store.read(artifact_id)
        == raw
        == canonical_bytes(recovered.signed_record)
    )
    assert not recovered.publication.wrote


def test_two_processes_apply_one_stable_command(registry, tmp_path, database_url):
    import json
    import subprocess
    import sys

    installation_file = tmp_path / "ephemeral-installation.json"
    installation_file.write_bytes(
        canonical_bytes(registry.installation.model_dump(mode="json"))
    )
    script = """
import sys
from pathlib import Path
from datetime import UTC, datetime, timedelta
from fundamental_service.fiscal_registry_runtime import FiscalRegistryInstallationV1, FiscalRegistryRuntime
from fundamental_service.metadata import PostgresMetadataStore, PostgresArtifactStore, PostgresContentStore
from fundamental_service.serialization import canonical_bytes
from fundamental_service.snapshots import SnapshotError
installation = FiscalRegistryInstallationV1.model_validate_json(Path(sys.argv[1]).read_bytes())
metadata = PostgresMetadataStore(sys.argv[2], auto_migrate=False)
try:
    metadata.start_read_only()
    artifacts = PostgresArtifactStore(metadata, PostgresContentStore(Path(sys.argv[3]), metadata))
    registry = FiscalRegistryRuntime(installation=installation, artifacts=artifacts, metadata=metadata)
    try:
        result = registry.apply(sys.argv[4], deadline_at=datetime.now(UTC)+timedelta(seconds=20))
        print(canonical_bytes({"signed": result.signed_record}).decode())
    except SnapshotError as error:
        print(canonical_bytes({"error": error.code}).decode())
finally:
    metadata.close()
"""
    command = [
        sys.executable,
        "-c",
        script,
        str(installation_file),
        database_url,
        str(tmp_path / "content"),
        registry.order.order_id,
    ]
    children = [
        subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for _ in range(2)
    ]
    try:
        outputs = [child.communicate(timeout=30) for child in children]
        assert all(child.returncode == 0 for child in children), outputs
        results = [json.loads(out) for out, _ in outputs]
        successful = [result["signed"] for result in results if "signed" in result]
        assert successful
        assert all(value == successful[0] for value in successful)
        assert all(
            result.get("error") in {None, "FISCAL_REGISTRY_IN_FLIGHT"}
            for result in results
        ), results
        repeated = registry.runtime.apply(
            registry.order.order_id, deadline_at=deadline()
        )
        assert canonical_bytes(repeated.signed_record) == canonical_bytes(successful[0])
        assert not repeated.publication.wrote
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)


def test_orphan_a_restore_b_refuses_old_order_and_fresh_b_succeeds(
    registry, monkeypatch, tmp_path, database_url
):
    import asyncio
    from fundamental_service.fiscal_admission_history import (
        PostgresFiscalAdmissionHistory,
    )
    from fundamental_service.persistence_recovery import (
        export_backup,
        restore_backup,
        _verify_bundle,
    )
    from fundamental_service.metadata import PostgresMetadataStore
    from test_fiscal_history_recovery import target_pin
    from test_fiscal_admission_history import _temporary_database

    original = registry.base.store.put_bytes_with_receipt

    def crash(artifact_id, *args, **kwargs):
        if artifact_id == fiscal_authority_command_artifact_id(registry.order.command):
            raise RuntimeError("orphan signature in source epoch")
        return original(artifact_id, *args, **kwargs)

    monkeypatch.setattr(registry.base.store, "put_bytes_with_receipt", crash)
    with pytest.raises(RuntimeError, match="orphan signature"):
        registry.runtime.apply(registry.order.order_id, deadline_at=deadline())
    monkeypatch.setattr(registry.base.store, "put_bytes_with_receipt", original)
    registry.base.metadata.close()
    receipt = asyncio.run(
        export_backup(
            database_url,
            tmp_path / "content",
            tmp_path / "backups",
            source_revision="a" * 40,
        )
    )
    bundle = tmp_path / "backups" / receipt.manifest_digest
    manifest = _verify_bundle(bundle, receipt.manifest_digest)
    with _temporary_database(os.environ["FUNDAMENTAL_TEST_DATABASE_URL"]) as target:
        with target_pin(target, manifest, tmp_path / "pin.json") as pin:
            restored = asyncio.run(
                restore_backup(
                    target,
                    tmp_path / "target",
                    bundle,
                    manifest_digest=manifest.digest,
                    authorization_path=pin,
                )
            )
            assert restored.target_origin_id != registry.order.issuance.origin_id
            metadata = PostgresMetadataStore(target, auto_migrate=False)
            try:
                metadata.start_read_only()
                store = PostgresArtifactStore(
                    metadata, PostgresContentStore(tmp_path / "target", metadata)
                )
                runtime = FiscalRegistryRuntime(
                    installation=registry.installation,
                    artifacts=store,
                    metadata=metadata,
                )
                with pytest.raises(SnapshotError, match="another issuance epoch"):
                    runtime.apply(registry.order.order_id, deadline_at=deadline())
                now = datetime.now(UTC)
                fresh = registry.order.model_copy(
                    update={
                        "order_id": "fresh-b",
                        "issuance": PostgresFiscalAdmissionHistory(metadata)
                        .read_epoch(deadline_at=deadline())
                        .issuance_context,
                        "command": registry.order.command.model_copy(
                            update={"command_id": "fresh-b-grant"}
                        ),
                        "valid_from": now,
                    }
                )
                registry.write(fresh)
                result = runtime.apply(fresh.order_id, deadline_at=deadline())
                assert result.signed_record.issuance == fresh.issuance
                reader = build_fiscal_registry_reader(
                    deployment_file=registry.installation.deployment_file,
                    deployment_uid=os.getuid(),
                    artifacts=store,
                    metadata=metadata,
                )
                assert (
                    reader.read_current(
                        "synthetic-classifier",
                        expected_role="classifier",
                        deadline_at=deadline(),
                    ).grant_ref.artifact_id
                    == result.signed_record.artifact_id
                )
            finally:
                metadata.close()


def test_lost_attempt_after_durable_marker_cannot_sign_or_be_retried(
    registry, monkeypatch
):
    original = registry.base.store.put_bytes_with_receipt

    def lose(artifact_id, *args, **kwargs):
        result = original(artifact_id, *args, **kwargs)
        if artifact_id.endswith(":signing"):
            leases = tuple(registry.base.metadata._ingestion_lock_connections)
            assert len(leases) == 1
            from fundamental_service.metadata import IngestionLockLease

            identity = leases[0]
            key, _ = registry.base.metadata._ingestion_lock_connections[identity]
            registry.base.metadata.release_ingestion_lock(
                IngestionLockLease(identity, key)
            )
        return result

    monkeypatch.setattr(registry.base.store, "put_bytes_with_receipt", lose)
    with pytest.raises(SnapshotError) as lost:
        registry.runtime.apply(registry.order.order_id, deadline_at=deadline())
    assert lost.value.code == "INGESTION_LOCK_LOST"
    monkeypatch.setattr(registry.base.store, "put_bytes_with_receipt", original)
    with pytest.raises(SnapshotError) as unknown:
        registry.runtime.apply(registry.order.order_id, deadline_at=deadline())
    assert unknown.value.code == "FISCAL_REGISTRY_SIGNING_OUTCOME_UNAVAILABLE"
    assert not registry.base.metadata._ingestion_lock_connections


def test_empty_control_presence_does_not_relax_strict_reader(registry):
    stream = "control:fiscal-authority:" + registry.order.command.authority_id
    history = registry.runtime._history
    assert history.read_if_present(stream, deadline_at=deadline()) is None
    with pytest.raises(SnapshotError) as strict:
        history.read((stream,), deadline_at=deadline())
    assert strict.value.code == "FISCAL_ADMISSION_HISTORY_UNAVAILABLE"
    registry.runtime.apply(registry.order.order_id, deadline_at=deadline())
    optional = history.read_if_present(stream, deadline_at=deadline())
    strict = history.read((stream,), deadline_at=deadline())
    assert optional.entries == strict.entries and optional.heads == strict.heads
