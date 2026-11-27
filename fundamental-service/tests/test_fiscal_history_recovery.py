from __future__ import annotations

import asyncio
import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import text

from fundamental_service.data_releases import ArtifactRefV1
from fundamental_service.fiscal_admission_history import (
    PostgresFiscalAdmissionHistory,
    FiscalControlBindingV1,
)
from fundamental_service.history_recovery_contracts import RecoveryAuthorizationV1
from fundamental_service.metadata import (
    PostgresMetadataStore,
    PostgresArtifactStore,
    PostgresContentStore,
)
from fundamental_service.persistence_recovery import (
    export_backup,
    restore_backup,
    _database_identity,
    _connect,
    _verify_bundle,
    RecoveryError,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
from test_fiscal_admission_history import _temporary_database


def deadline():
    return datetime.now(UTC) + timedelta(seconds=20)


@contextmanager
def target_pin(url, manifest, path):
    role = "issue532_runtime_" + uuid4().hex

    async def prepare():
        connection = await _connect(url)
        try:
            await connection.execute(f'CREATE ROLE "{role}" NOLOGIN')
            identity = await _database_identity(connection)
            return RecoveryAuthorizationV1(
                manifest_digest=manifest.digest,
                source_origin_id=manifest.history_frontier.origin_id,
                expected_target=identity,
                runtime_role=role,
                source_fence_reference="synthetic:stopped-source",
            )
        finally:
            await connection.close()

    auth = asyncio.run(prepare())
    path.write_bytes(canonical_bytes(auth))
    path.chmod(0o600)
    try:
        yield path
    finally:

        async def clean():
            connection = await _connect(url)
            try:
                await connection.execute(f'DROP ROLE "{role}"')
            finally:
                await connection.close()

        asyncio.run(clean())


@pytest.fixture
def databases():
    base = os.getenv("FUNDAMENTAL_TEST_DATABASE_URL")
    if not base:
        pytest.skip("requires isolated PostgreSQL")
    with (
        _temporary_database(base) as source,
        _temporary_database(base) as target,
        _temporary_database(base) as third,
    ):
        yield source, target, third


def store(url, path):
    metadata = PostgresMetadataStore(url, auto_migrate=True)
    metadata.start()
    path.mkdir(exist_ok=True)
    return metadata, PostgresArtifactStore(
        metadata, PostgresContentStore(path, metadata)
    )


@pytest.mark.parametrize("sealed", [False, True])
def test_official_export_restore_preserves_sealed_history_and_new_local_origin(
    databases, tmp_path, sealed
):
    source, target, _ = databases
    metadata, artifacts = store(source, tmp_path / "source")
    history = PostgresFiscalAdmissionHistory(metadata)
    old = None
    if sealed:
        record = artifacts.put_with_receipt(
            "synthetic-source", {"synthetic": True}
        ).artifact
        checkpoint = history.checkpoint((record,), deadline_at=deadline())

        async def invalidate(connection):
            await connection.execute(
                text(
                    "UPDATE fundamental.artifact_references SET status='invalidated' WHERE artifact_id='synthetic-source'"
                )
            )

        metadata.run_fiscal_admission_history(invalidate)
        old = history.seal_pending(
            ("evidence:synthetic-source",), deadline_at=deadline()
        )
    metadata.close()
    receipt = asyncio.run(
        export_backup(
            source, tmp_path / "source", tmp_path / "backups", source_revision="f" * 40
        )
    )
    bundle = tmp_path / "backups" / receipt.manifest_digest
    manifest = _verify_bundle(bundle, receipt.manifest_digest)
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
        assert (
            restored.wrote
            and restored.target_origin_id != manifest.history_frontier.origin_id
        )
        assert not asyncio.run(
            restore_backup(
                target,
                tmp_path / "target",
                bundle,
                manifest_digest=manifest.digest,
                authorization_path=pin,
            )
        ).wrote
        current, _ = store(target, tmp_path / "target")
        try:
            if sealed:
                read = PostgresFiscalAdmissionHistory(current).read(
                    ("evidence:synthetic-source",), deadline_at=deadline()
                )
                assert [entry.payload_bytes for entry in read.entries] == [
                    entry.payload_bytes for entry in old.entries
                ]
                assert [entry.commit_bound for entry in read.entries] == [
                    entry.commit_bound for entry in old.entries
                ]
                assert (
                    read.evidence_as_of(
                        "synthetic-source", at=checkpoint.observed_through
                    ).status
                    == "valid"
                )
                assert (
                    read.evidence_as_of(
                        "synthetic-source", at=manifest.history_frontier.covered_through
                    ).status
                    == "invalidated"
                )
                with pytest.raises(SnapshotError, match="recovery_gap"):
                    read.evidence_as_of("synthetic-source", at=read.observed_through)
                with pytest.raises(SnapshotError, match="fresh local"):
                    read.require_current_epoch((read.entries[0],))
        finally:
            current.close()


def test_reexport_keeps_ancestor_gaps_and_same_operation_retry_preserves_local_appends(
    databases, tmp_path
):
    source, target, third = databases
    metadata, artifacts = store(source, tmp_path / "source")
    item = artifacts.put_with_receipt("synthetic:control", {"synthetic": True}).artifact
    command = FiscalControlBindingV1(
        action="authority_granted",
        payload_ref=ArtifactRefV1(
            role="synthetic-control",
            artifact_id=item.artifact_id,
            content_hash=item.content_hash,
            media_type=item.media_type,
        ),
        command_digest=sha256_digest("first"),
    )
    history = PostgresFiscalAdmissionHistory(metadata)
    original = history.append_once(
        "synthetic:role", command, expected_head=None, deadline_at=deadline()
    )
    metadata.close()
    exported = asyncio.run(
        export_backup(
            source, tmp_path / "source", tmp_path / "backups", source_revision="f" * 40
        )
    )
    bundle = tmp_path / "backups" / exported.manifest_digest
    manifest = _verify_bundle(bundle, exported.manifest_digest)
    with target_pin(target, manifest, tmp_path / "first-pin.json") as pin:
        first = asyncio.run(
            restore_backup(
                target,
                tmp_path / "target",
                bundle,
                manifest_digest=manifest.digest,
                authorization_path=pin,
            )
        )
        middle, middle_artifacts = store(target, tmp_path / "target")
        middle_history = PostgresFiscalAdmissionHistory(middle)
        read = middle_history.read(("control:synthetic:role",), deadline_at=deadline())
        local_command = command.model_copy(
            update={"command_digest": sha256_digest("second")}
        )
        appended = middle_history.append_once(
            "synthetic:role",
            local_command,
            expected_head=read.heads[0],
            deadline_at=deadline(),
        )
        local = middle_history.read(("control:synthetic:role",), deadline_at=deadline())
        local.require_current_epoch((appended.entry,))
        assert len(local.entries) == 2
        repeat = asyncio.run(
            restore_backup(
                target,
                tmp_path / "target",
                bundle,
                manifest_digest=manifest.digest,
                authorization_path=pin,
            )
        )
        assert not repeat.wrote and repeat.activation == first.activation
        assert (
            len(
                middle_history.read(
                    ("control:synthetic:role",), deadline_at=deadline()
                ).entries
            )
            == 2
        )
        middle.close()
        second_export = asyncio.run(
            export_backup(
                target,
                tmp_path / "target",
                tmp_path / "backups",
                source_revision="f" * 40,
            )
        )
        second_bundle = tmp_path / "backups" / second_export.manifest_digest
        second_manifest = _verify_bundle(second_bundle, second_export.manifest_digest)
        with target_pin(
            third, second_manifest, tmp_path / "second-pin.json"
        ) as second_pin:
            asyncio.run(
                restore_backup(
                    third,
                    tmp_path / "third",
                    second_bundle,
                    manifest_digest=second_manifest.digest,
                    authorization_path=second_pin,
                )
            )
            last, _ = store(third, tmp_path / "third")
            try:
                final = PostgresFiscalAdmissionHistory(last).read(
                    ("control:synthetic:role",), deadline_at=deadline()
                )
                assert len(final.epoch.cutovers) == 2
                assert final.entries[0].payload_bytes == original.entry.payload_bytes
                assert final.entries[1].payload_bytes == appended.entry.payload_bytes
                for cutover in final.epoch.cutovers:
                    with pytest.raises(
                        SnapshotError,
                        match="recovery_gap|activation_visibility_ambiguous",
                    ):
                        final.prefix_as_of(
                            "control:synthetic:role",
                            at=cutover.source_frontier_at + timedelta(microseconds=1),
                        )
                with pytest.raises(SnapshotError, match="fresh local"):
                    final.require_current_epoch((final.entries[1],))
            finally:
                last.close()


def test_low_privilege_runtime_cannot_enter_recovery_or_forge_foreign_history(
    databases, tmp_path
):
    from sqlalchemy.engine import make_url

    source, target, _ = databases
    metadata, artifacts = store(source, tmp_path / "source")
    record = artifacts.put_with_receipt(
        "synthetic-control", {"synthetic": True}
    ).artifact
    history = PostgresFiscalAdmissionHistory(metadata)
    command = FiscalControlBindingV1(
        action="authority_granted",
        payload_ref=ArtifactRefV1(
            role="synthetic-control",
            artifact_id=record.artifact_id,
            content_hash=record.content_hash,
            media_type=record.media_type,
        ),
        command_digest=sha256_digest("synthetic"),
    )
    history.append_once(
        "synthetic-role", command, expected_head=None, deadline_at=deadline()
    )
    metadata.close()
    receipt = asyncio.run(
        export_backup(
            source, tmp_path / "source", tmp_path / "backups", source_revision="f" * 40
        )
    )
    bundle = tmp_path / "backups" / receipt.manifest_digest
    manifest = _verify_bundle(bundle, receipt.manifest_digest)
    with target_pin(target, manifest, tmp_path / "pin.json") as pin:
        asyncio.run(
            restore_backup(
                target,
                tmp_path / "target",
                bundle,
                manifest_digest=manifest.digest,
                authorization_path=pin,
            )
        )
        authorization = RecoveryAuthorizationV1.model_validate_json(pin.read_bytes())
        password = uuid4().hex

        async def check():
            owner = await _connect(target)
            role = authorization.runtime_role
            try:
                await owner.execute(
                    f"ALTER ROLE \"{role}\" LOGIN PASSWORD '{password}'"
                )
                await owner.execute(f'GRANT USAGE ON SCHEMA fundamental TO "{role}"')
                await owner.execute(
                    f'GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA fundamental TO "{role}"'
                )
                runtime_url = (
                    make_url(target)
                    .set(drivername="postgresql", username=role, password=password)
                    .render_as_string(hide_password=False)
                )
                runtime = await asyncpg.connect(runtime_url)
                try:
                    statements = (
                        "SELECT fundamental.fiscal_recovery_freeze_stage()",
                        "SELECT fundamental.fiscal_history_activate(fundamental.fiscal_history_origin_id())",
                        "INSERT INTO fundamental_recovery.context VALUES(pg_backend_pid(),pg_current_xact_id(),gen_random_uuid(),'x','x',NULL)",
                        "SET ROLE fundamental",
                        "ALTER TABLE fundamental.fiscal_history_events DISABLE TRIGGER ALL",
                        "SET session_replication_role=replica",
                        "UPDATE fundamental.fiscal_history_events SET event_digest=repeat('0',64)",
                        "DELETE FROM fundamental.fiscal_history_commit_receipts",
                    )
                    for statement in statements:
                        with pytest.raises(asyncpg.PostgresError):
                            await runtime.execute(statement)
                    with pytest.raises(asyncpg.PostgresError):
                        await runtime.execute(
                            "INSERT INTO fundamental.fiscal_history_origin VALUES(gen_random_uuid(),'spoof',1,1)"
                        )
                    with pytest.raises(asyncpg.PostgresError):
                        await runtime.execute(
                            "INSERT INTO fundamental.fiscal_history_events SELECT stream_id,sequence+1,event_digest,payload_bytes,command_digest,origin_id,writer_xid8 FROM fundamental.fiscal_history_events LIMIT 1"
                        )
                    with pytest.raises(asyncpg.PostgresError):
                        await runtime.execute(
                            "INSERT INTO fundamental.fiscal_history_activation_receipts VALUES(fundamental.fiscal_history_origin_id(),clock_timestamp(),clock_timestamp())"
                        )
                finally:
                    await runtime.close()
            finally:
                await owner.execute(
                    f'REVOKE ALL ON ALL TABLES IN SCHEMA fundamental FROM "{role}"'
                )
                await owner.execute(f'REVOKE ALL ON SCHEMA fundamental FROM "{role}"')
                await owner.close()

        asyncio.run(check())


@pytest.mark.parametrize(
    ("privilege", "membership", "permitted"),
    [
        ("schema_create", "direct", False),
        ("schema_create", "indirect", False),
        ("recovery_usage", "direct", False),
        ("recovery_create", "direct", False),
        ("freeze_execute", "direct", False),
        ("activate_execute", "direct", False),
        ("createrole", "direct", False),
        ("bypassrls", "direct", False),
        ("none", "admin_direct", False),
        ("none", "admin_set_middle", False),
        ("none", "admin_inherit_middle", False),
        ("none", "indirect", True),
        ("schema_create", "blocked", True),
    ],
)
def test_official_restore_checks_runtime_assumable_roles(
    databases, tmp_path, privilege, membership, permitted
):
    from sqlalchemy.engine import make_url

    source, target, _ = databases
    source_store, _ = store(source, tmp_path / "source")
    source_store.close()
    target_store, _ = store(target, tmp_path / "target")
    target_store.close()
    receipt = asyncio.run(
        export_backup(
            source, tmp_path / "source", tmp_path / "backups", source_revision="f" * 40
        )
    )
    bundle = tmp_path / "backups" / receipt.manifest_digest
    manifest = _verify_bundle(bundle, receipt.manifest_digest)
    with target_pin(target, manifest, tmp_path / "pin.json") as pin:
        authorization = RecoveryAuthorizationV1.model_validate_json(pin.read_bytes())
        runtime = authorization.runtime_role
        middle = "issue532_middle_" + uuid4().hex
        privileged = "issue532_privileged_" + uuid4().hex
        password = uuid4().hex

        async def configure_and_prove():
            owner = await _connect(target)
            try:
                for role in (middle, privileged):
                    await owner.execute(f'CREATE ROLE "{role}" NOLOGIN NOINHERIT')
                await owner.execute(
                    f"ALTER ROLE \"{runtime}\" LOGIN NOINHERIT PASSWORD '{password}'"
                )
                grants = {
                    "schema_create": f'GRANT CREATE ON SCHEMA fundamental TO "{privileged}"',
                    "recovery_usage": f'GRANT USAGE ON SCHEMA fundamental_recovery TO "{privileged}"',
                    "recovery_create": f'GRANT CREATE ON SCHEMA fundamental_recovery TO "{privileged}"',
                    "freeze_execute": f'GRANT EXECUTE ON FUNCTION fundamental.fiscal_recovery_freeze_stage() TO "{privileged}"',
                    "activate_execute": f'GRANT EXECUTE ON FUNCTION fundamental.fiscal_history_activate(uuid) TO "{privileged}"',
                    "createrole": f'ALTER ROLE "{privileged}" CREATEROLE',
                    "bypassrls": f'ALTER ROLE "{privileged}" BYPASSRLS',
                }
                if privilege != "none":
                    await owner.execute(grants[privilege])
                indirect = membership in {
                    "indirect",
                    "admin_set_middle",
                    "admin_inherit_middle",
                }
                if indirect:
                    inherited = membership == "admin_inherit_middle"
                    await owner.execute(
                        f'GRANT "{middle}" TO "{runtime}" WITH ADMIN FALSE, '
                        f"INHERIT {str(inherited).upper()}, SET {str(not inherited).upper()}"
                    )
                member = middle if indirect else runtime
                admin = membership.startswith("admin_")
                can_set = not admin and membership != "blocked"
                await owner.execute(
                    f'GRANT "{privileged}" TO "{member}" WITH ADMIN {str(admin).upper()}, '
                    f"INHERIT FALSE, SET {str(can_set).upper()}"
                )
                runtime_url = (
                    make_url(target)
                    .set(drivername="postgresql", username=runtime, password=password)
                    .render_as_string(hide_password=False)
                )
                normal = await asyncpg.connect(runtime_url)
                try:
                    assert await normal.fetchval("SELECT current_user") == runtime
                    if can_set:
                        await normal.execute(f'SET ROLE "{privileged}"')
                        assert (
                            await normal.fetchval("SELECT current_user") == privileged
                        )
                    else:
                        with pytest.raises(asyncpg.InsufficientPrivilegeError):
                            await normal.execute(f'SET ROLE "{privileged}"')
                    if admin:
                        transaction = normal.transaction()
                        await transaction.start()
                        try:
                            if membership == "admin_set_middle":
                                await normal.execute(f'SET ROLE "{middle}"')
                            await normal.execute(
                                f'GRANT "{privileged}" TO "{runtime}" WITH SET TRUE'
                            )
                            assert await normal.fetchval(
                                "SELECT pg_has_role(session_user,$1::name,'SET')",
                                privileged,
                            )
                        finally:
                            await transaction.rollback()
                        assert not await normal.fetchval(
                            "SELECT pg_has_role(session_user,$1::name,'SET')",
                            privileged,
                        )
                finally:
                    await normal.close()
            finally:
                await owner.close()

        async def clean():
            owner = await _connect(target)
            try:
                for role in (middle, privileged):
                    await owner.execute(f'DROP OWNED BY "{role}" CASCADE')
                    await owner.execute(f'DROP ROLE "{role}"')
            finally:
                await owner.close()

        try:
            asyncio.run(configure_and_prove())
            operation = restore_backup(
                target,
                tmp_path / "target",
                bundle,
                manifest_digest=manifest.digest,
                authorization_path=pin,
            )
            if permitted:
                assert asyncio.run(operation).wrote
            else:
                with pytest.raises(RecoveryError, match="runtime role"):
                    asyncio.run(operation)
        finally:
            asyncio.run(clean())


@pytest.mark.parametrize(
    ("capability", "membership"),
    [
        (role, membership)
        for role in (
            "pg_read_server_files",
            "pg_write_server_files",
            "pg_execute_server_program",
        )
        for membership in ("direct", "set", "inherit", "blocked")
    ]
    + [
        (signature, "direct")
        for signature in (
            "pg_read_file(text)",
            "pg_read_file(text,boolean)",
            "pg_read_file(text,bigint,bigint)",
            "pg_read_file(text,bigint,bigint,boolean)",
            "pg_read_binary_file(text)",
            "pg_read_binary_file(text,boolean)",
            "pg_read_binary_file(text,bigint,bigint)",
            "pg_read_binary_file(text,bigint,bigint,boolean)",
            "lo_import(text)",
            "lo_import(text,oid)",
            "lo_export(oid,text)",
        )
    ]
    + [
        (signature, membership)
        for signature in (
            "pg_read_file(text,boolean)",
            "pg_read_binary_file(text,boolean)",
            "lo_import(text)",
            "lo_export(oid,text)",
        )
        for membership in ("set", "inherit", "blocked")
    ]
    + [
        ("pg_read_file(text,boolean)", "public"),
        ("pg_stat_file(text,boolean)", "direct"),
    ],
)
def test_restore_checks_server_io_capabilities_without_executing_them(
    databases, tmp_path, capability, membership
):
    from sqlalchemy.engine import make_url

    source, target, _ = databases
    source_store, _ = store(source, tmp_path / "source")
    source_store.close()
    target_store, _ = store(target, tmp_path / "target")
    target_store.close()
    receipt = asyncio.run(
        export_backup(
            source, tmp_path / "source", tmp_path / "backups", source_revision="f" * 40
        )
    )
    bundle = tmp_path / "backups" / receipt.manifest_digest
    manifest = _verify_bundle(bundle, receipt.manifest_digest)
    with target_pin(target, manifest, tmp_path / "pin.json") as pin:
        authorization = RecoveryAuthorizationV1.model_validate_json(pin.read_bytes())
        runtime = authorization.runtime_role
        holder = "issue532_io_" + uuid4().hex
        password = uuid4().hex
        is_function = "(" in capability
        query = (
            "SELECT has_function_privilege(current_user,$1::regprocedure,'EXECUTE')"
            if is_function
            else "SELECT pg_has_role(current_user,$1::name,'USAGE')"
        )

        async def configure_and_prove():
            owner = await _connect(target)
            try:
                await owner.execute(f'CREATE ROLE "{holder}" NOLOGIN NOINHERIT')
                await owner.execute(
                    f"ALTER ROLE \"{runtime}\" LOGIN NOINHERIT PASSWORD '{password}'"
                )
                recipient = runtime if membership == "direct" else holder
                if is_function:
                    recipient = "PUBLIC" if membership == "public" else f'"{recipient}"'
                    await owner.execute(
                        f"GRANT EXECUTE ON FUNCTION pg_catalog.{capability} TO {recipient}"
                    )
                else:
                    await owner.execute(
                        f'GRANT "{capability}" TO "{recipient}" '
                        "WITH ADMIN FALSE, INHERIT TRUE, SET FALSE"
                    )
                if membership not in {"direct", "public"}:
                    await owner.execute(
                        f'GRANT "{holder}" TO "{runtime}" WITH ADMIN FALSE, '
                        f"INHERIT {str(membership == 'inherit').upper()}, "
                        f"SET {str(membership == 'set').upper()}"
                    )
                runtime_url = (
                    make_url(target)
                    .set(drivername="postgresql", username=runtime, password=password)
                    .render_as_string(hide_password=False)
                )
                normal = await asyncpg.connect(runtime_url)
                try:
                    assert await normal.fetchval("SELECT current_user") == runtime
                    if membership == "set":
                        assert not await normal.fetchval(query, capability)
                        await normal.execute(f'SET ROLE "{holder}"')
                        assert await normal.fetchval("SELECT current_user") == holder
                    assert await normal.fetchval(query, capability) is (
                        membership != "blocked"
                    )
                finally:
                    await normal.close()
            finally:
                await owner.close()

        async def clean():
            owner = await _connect(target)
            try:
                if is_function and membership in {"direct", "public"}:
                    recipient = "PUBLIC" if membership == "public" else f'"{runtime}"'
                    await owner.execute(
                        f"REVOKE EXECUTE ON FUNCTION pg_catalog.{capability} FROM {recipient}"
                    )
                await owner.execute(f'DROP OWNED BY "{holder}" CASCADE')
                await owner.execute(f'DROP ROLE "{holder}"')
            finally:
                await owner.close()

        try:
            asyncio.run(configure_and_prove())
            operation = restore_backup(
                target,
                tmp_path / "target",
                bundle,
                manifest_digest=manifest.digest,
                authorization_path=pin,
            )
            if membership == "blocked" or capability == "pg_stat_file(text,boolean)":
                assert asyncio.run(operation).wrote
            else:
                with pytest.raises(RecoveryError, match="runtime role"):
                    asyncio.run(operation)
        finally:
            asyncio.run(clean())


@pytest.mark.parametrize("offset_seconds", [-4, 4])
def test_restore_observes_activation_with_database_clock(
    databases, tmp_path, monkeypatch, offset_seconds
):
    from fundamental_service import persistence_recovery as recovery

    class HostClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(seconds=offset_seconds)

    source, target, _ = databases
    metadata, _ = store(source, tmp_path / "source")
    metadata.close()
    receipt = asyncio.run(
        export_backup(
            source, tmp_path / "source", tmp_path / "backups", source_revision="f" * 40
        )
    )
    bundle = tmp_path / "backups" / receipt.manifest_digest
    manifest = _verify_bundle(bundle, receipt.manifest_digest)
    with target_pin(target, manifest, tmp_path / "pin.json") as pin:
        monkeypatch.setattr(recovery, "datetime", HostClock)
        restored = asyncio.run(
            restore_backup(
                target,
                tmp_path / "target",
                bundle,
                manifest_digest=manifest.digest,
                authorization_path=pin,
                deadline_at=deadline(),
            )
        )
        assert restored.wrote
        assert (
            restored.history_frontier.covered_through
            < restored.activation.committed_at
            <= restored.activation.visible_by
        )


def test_restore_refuses_unproven_database_clock_and_retries_same_activation(
    databases, tmp_path, monkeypatch
):
    from fundamental_service import persistence_recovery as recovery

    source, target, _ = databases
    metadata, _ = store(source, tmp_path / "source")
    metadata.close()
    receipt = asyncio.run(
        export_backup(
            source, tmp_path / "source", tmp_path / "backups", source_revision="f" * 40
        )
    )
    bundle = tmp_path / "backups" / receipt.manifest_digest
    manifest = _verify_bundle(bundle, receipt.manifest_digest)
    connect = recovery._connect
    observed = []

    class ReversedClockConnection:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        async def fetchrow(self, query, *args):
            row = await self.connection.fetchrow(query, *args)
            if query.startswith("SELECT committed_at,visible_by FROM") and row:
                observed.append(row["visible_by"])
            return row

        async def fetchval(self, query, *args):
            if query == "SELECT clock_timestamp()" and observed:
                return observed[-1]
            return await self.connection.fetchval(query, *args)

    async def reversed_clock_connection(url):
        return ReversedClockConnection(await connect(url))

    with target_pin(target, manifest, tmp_path / "pin.json") as pin:
        with monkeypatch.context() as patch:
            patch.setattr(recovery, "_connect", reversed_clock_connection)
            with pytest.raises(RecoveryError, match="activation clock"):
                asyncio.run(
                    restore_backup(
                        target,
                        tmp_path / "target",
                        bundle,
                        manifest_digest=manifest.digest,
                        authorization_path=pin,
                    )
                )
        retried = asyncio.run(
            restore_backup(
                target,
                tmp_path / "target",
                bundle,
                manifest_digest=manifest.digest,
                authorization_path=pin,
            )
        )
        assert not retried.wrote
        assert observed == [retried.activation.visible_by]


def test_export_locks_before_snapshot_and_seals_a_writer_that_commits_during_lock_wait(
    databases, tmp_path
):
    source, _, _ = databases
    metadata, artifacts = store(source, tmp_path / "source")
    record = artifacts.put_with_receipt(
        "synthetic:locked-source", {"synthetic": True}
    ).artifact
    PostgresFiscalAdmissionHistory(metadata).checkpoint(
        (record,), deadline_at=deadline()
    )
    metadata.close()

    async def run():
        writer = await _connect(source)
        observer = await _connect(source)
        transaction = writer.transaction()
        await transaction.start()
        await writer.execute(
            "UPDATE fundamental.artifact_references SET status='invalidated' WHERE artifact_id='synthetic:locked-source'"
        )
        operation = asyncio.create_task(
            export_backup(
                source,
                tmp_path / "source",
                tmp_path / "backups",
                source_revision="f" * 40,
                deadline_at=deadline(),
            )
        )
        try:
            for _ in range(100):
                blocked = await observer.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE 'LOCK TABLE%')"
                )
                if blocked:
                    break
                await asyncio.sleep(0.01)
            assert blocked
            await transaction.commit()
            result = await operation
            return result
        finally:
            if not operation.done():
                await transaction.rollback()
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)
            await writer.close()
            await observer.close()

    receipt = asyncio.run(run())
    bundle = tmp_path / "backups" / receipt.manifest_digest
    manifest = _verify_bundle(bundle, receipt.manifest_digest)
    from fundamental_service.persistence_recovery import _backup_tables

    rows = _backup_tables(bundle, manifest)
    assert rows["artifact_references"][0]["status"] == "invalidated"
    assert len(rows["fiscal_history_events"]) == 2
    assert len(rows["fiscal_history_commit_receipts"]) == 2


def test_post_backup_revocation_cannot_be_revived_by_restoring_old_control(
    databases, tmp_path
):
    source, target, _ = databases
    metadata, artifacts = store(source, tmp_path / "source")
    item = artifacts.put_with_receipt("synthetic:grant", {"synthetic": True}).artifact
    command = FiscalControlBindingV1(
        action="authority_granted",
        payload_ref=ArtifactRefV1(
            role="synthetic-control",
            artifact_id=item.artifact_id,
            content_hash=item.content_hash,
            media_type=item.media_type,
        ),
        command_digest=sha256_digest("grant"),
    )
    history = PostgresFiscalAdmissionHistory(metadata)
    granted = history.append_once(
        "synthetic:classifier", command, expected_head=None, deadline_at=deadline()
    )
    exported = asyncio.run(
        export_backup(
            source, tmp_path / "source", tmp_path / "backups", source_revision="f" * 40
        )
    )
    revoked = command.model_copy(
        update={
            "action": "authority_revoked",
            "command_digest": sha256_digest("revoke"),
        }
    )
    history.append_once(
        "synthetic:classifier",
        revoked,
        expected_head=history.read(
            ("control:synthetic:classifier",), deadline_at=deadline()
        ).heads[0],
        deadline_at=deadline(),
    )
    metadata.close()
    bundle = tmp_path / "backups" / exported.manifest_digest
    manifest = _verify_bundle(bundle, exported.manifest_digest)
    with target_pin(target, manifest, tmp_path / "pin.json") as pin:
        asyncio.run(
            restore_backup(
                target,
                tmp_path / "target",
                bundle,
                manifest_digest=manifest.digest,
                authorization_path=pin,
            )
        )
        restored, restored_artifacts = store(target, tmp_path / "target")
        try:
            restored_history = PostgresFiscalAdmissionHistory(restored)
            read = restored_history.read(
                ("control:synthetic:classifier",), deadline_at=deadline()
            )
            assert len(read.entries) == 1
            assert read.entries[0].payload_bytes == granted.entry.payload_bytes
            with pytest.raises(SnapshotError, match="fresh local"):
                read.require_current_epoch((read.entries[0],))
            with pytest.raises(SnapshotError, match="recovery_gap"):
                read.prefix_as_of(
                    "control:synthetic:classifier", at=read.observed_through
                )
        finally:
            restored.close()


def test_expired_deadline_refuses_a_real_locked_restore_and_retry_recovers(
    databases, tmp_path
):
    source, target, _ = databases
    metadata, _ = store(source, tmp_path / "source")
    metadata.close()
    exported = asyncio.run(
        export_backup(
            source, tmp_path / "source", tmp_path / "backups", source_revision="f" * 40
        )
    )
    bundle = tmp_path / "backups" / exported.manifest_digest
    manifest = _verify_bundle(bundle, exported.manifest_digest)
    target_metadata, _ = store(target, tmp_path / "target")
    target_metadata.close()
    with target_pin(target, manifest, tmp_path / "pin.json") as pin:

        async def run():
            blocker = await _connect(target)
            transaction = blocker.transaction()
            await transaction.start()
            await blocker.execute(
                "LOCK TABLE fundamental.artifact_references IN ACCESS EXCLUSIVE MODE"
            )
            try:
                with pytest.raises(RecoveryError, match="deadline"):
                    await restore_backup(
                        target,
                        tmp_path / "target",
                        bundle,
                        manifest_digest=manifest.digest,
                        authorization_path=pin,
                        deadline_at=datetime.now(UTC) + timedelta(milliseconds=150),
                    )
                assert (
                    await blocker.fetchval(
                        "SELECT count(*) FROM fundamental.fiscal_history_restore_links"
                    )
                    == 0
                )
            finally:
                await transaction.rollback()
                await blocker.close()

        asyncio.run(run())
        assert asyncio.run(
            restore_backup(
                target,
                tmp_path / "target",
                bundle,
                manifest_digest=manifest.digest,
                authorization_path=pin,
            )
        ).wrote


def _seed_backup(source, tmp_path):
    metadata, artifacts = store(source, tmp_path / "source")
    record = artifacts.put_with_receipt(
        "synthetic:recovery", {"synthetic": True}
    ).artifact
    PostgresFiscalAdmissionHistory(metadata).checkpoint(
        (record,), deadline_at=deadline()
    )
    metadata.close()
    receipt = asyncio.run(
        export_backup(
            source, tmp_path / "source", tmp_path / "backups", source_revision="f" * 40
        )
    )
    bundle = tmp_path / "backups" / receipt.manifest_digest
    return bundle, _verify_bundle(bundle, receipt.manifest_digest)


@pytest.mark.parametrize("sealed", [False, True])
def test_cli_exports_and_restores_bootstrap_and_sealed_evidence(
    databases, tmp_path, sealed
):
    import subprocess
    import sys

    source, target, _ = databases
    source_root = tmp_path / "cli-source"
    source_root.mkdir()
    metadata, artifacts = store(source, source_root / "content")
    if sealed:
        record = artifacts.put_with_receipt(
            "synthetic:cli", {"synthetic": True}
        ).artifact
        PostgresFiscalAdmissionHistory(metadata).checkpoint(
            (record,), deadline_at=deadline()
        )
    metadata.close()

    def run_cli(url, root, *arguments):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "fundamental_service.persistence_recovery",
                *arguments,
            ],
            env={
                **os.environ,
                "FUNDAMENTAL_SERVICE_DATABASE_URL": url,
                "FUNDAMENTAL_SERVICE_DATA_ROOT": str(root),
            },
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
        return json.loads(result.stdout)

    exported = run_cli(
        source,
        source_root,
        "export",
        "--destination",
        str(tmp_path / "cli-backups"),
        "--source-revision",
        "f" * 40,
    )
    bundle = tmp_path / "cli-backups" / exported["manifest_digest"]
    manifest = _verify_bundle(bundle, exported["manifest_digest"])
    with target_pin(target, manifest, tmp_path / "pin.json") as pin:
        arguments = (
            "restore",
            "--bundle",
            str(bundle),
            "--manifest-digest",
            manifest.digest,
            "--authorization",
            str(pin),
        )
        restored = run_cli(target, tmp_path / "cli-target", *arguments)
        repeated = run_cli(target, tmp_path / "cli-target", *arguments)
        assert restored["wrote"] and not repeated["wrote"]
        assert restored["activation"] == repeated["activation"]
        assert restored["target_origin_id"] != manifest.history_frontier.origin_id


@pytest.mark.parametrize("after_activation", [False, True])
def test_committed_import_or_lost_activation_ack_retries_original_transaction(
    databases, tmp_path, monkeypatch, after_activation
):
    from fundamental_service import persistence_recovery as recovery

    source, target, _ = databases
    bundle, manifest = _seed_backup(source, tmp_path)
    activate = recovery._activate_import

    async def interrupted(connection, local):
        if after_activation:
            await activate(connection, local)
        raise RuntimeError("synthetic lost recovery acknowledgement")

    async def state():
        connection = await _connect(target)
        try:
            link = dict(
                await connection.fetchrow(
                    "SELECT target_origin_id::text, import_writer_xid8::text FROM fundamental.fiscal_history_restore_links"
                )
            )
            receipt = await connection.fetchrow(
                "SELECT * FROM fundamental.fiscal_history_activation_receipts"
            )
            return link, dict(receipt) if receipt else None
        finally:
            await connection.close()

    with target_pin(target, manifest, tmp_path / "pin.json") as pin:
        monkeypatch.setattr(recovery, "_activate_import", interrupted)
        with pytest.raises(RuntimeError, match="lost recovery acknowledgement"):
            asyncio.run(
                restore_backup(
                    target,
                    tmp_path / "target",
                    bundle,
                    manifest_digest=manifest.digest,
                    authorization_path=pin,
                )
            )
        pending_link, pending_receipt = asyncio.run(state())
        assert bool(pending_receipt) == after_activation
        monkeypatch.setattr(recovery, "_activate_import", activate)
        restored = asyncio.run(
            restore_backup(
                target,
                tmp_path / "target",
                bundle,
                manifest_digest=manifest.digest,
                authorization_path=pin,
            )
        )
        completed_link, completed_receipt = asyncio.run(state())
        assert not restored.wrote
        assert completed_link == pending_link
        if pending_receipt:
            assert completed_receipt == pending_receipt
        else:
            assert completed_receipt is not None


def test_pending_activation_refuses_lost_commit_proof_without_replacing_xid(
    databases, tmp_path, monkeypatch
):
    from fundamental_service import persistence_recovery as recovery

    source, target, _ = databases
    bundle, manifest = _seed_backup(source, tmp_path)
    activate = recovery._activate_import

    async def interrupted(connection, local):
        raise RuntimeError("synthetic interruption after metadata commit")

    async def lose_proof():
        connection = await _connect(target)
        try:
            writer = await connection.fetchval(
                "SELECT import_writer_xid8::text FROM fundamental.fiscal_history_restore_links"
            )
            await connection.execute(
                "CREATE OR REPLACE FUNCTION fundamental.fiscal_history_commit_lower(origin UUID, writer XID8) RETURNS JSONB LANGUAGE sql AS $$ SELECT jsonb_build_object('kind','missing','reason','commit_log_missing') $$"
            )
            return writer
        finally:
            await connection.close()

    with target_pin(target, manifest, tmp_path / "pin.json") as pin:
        monkeypatch.setattr(recovery, "_activate_import", interrupted)
        with pytest.raises(RuntimeError, match="after metadata commit"):
            asyncio.run(
                restore_backup(
                    target,
                    tmp_path / "target",
                    bundle,
                    manifest_digest=manifest.digest,
                    authorization_path=pin,
                )
            )
        writer = asyncio.run(lose_proof())
        monkeypatch.setattr(recovery, "_activate_import", activate)
        with pytest.raises(asyncpg.PostgresError, match="commit proof is unavailable"):
            asyncio.run(
                restore_backup(
                    target,
                    tmp_path / "target",
                    bundle,
                    manifest_digest=manifest.digest,
                    authorization_path=pin,
                )
            )

        async def check():
            connection = await _connect(target)
            try:
                assert (
                    await connection.fetchval(
                        "SELECT import_writer_xid8::text FROM fundamental.fiscal_history_restore_links"
                    )
                    == writer
                )
                assert (
                    await connection.fetchval(
                        "SELECT count(*) FROM fundamental.fiscal_history_activation_receipts"
                    )
                    == 0
                )
                assert not await connection.fetchval(
                    "SELECT fundamental.fiscal_history_local_ready()"
                )
            finally:
                await connection.close()

        asyncio.run(check())


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "mode",
        "symlink",
        "size",
        "uid",
        "target",
        "source",
        "digest",
        "runtime_owner",
        "runtime_missing",
    ],
)
def test_authorization_refusals_precede_metadata_import(
    databases, tmp_path, monkeypatch, damage
):
    from fundamental_service import persistence_recovery as recovery

    source, target, _ = databases
    metadata, _ = store(source, tmp_path / "source")
    metadata.close()
    exported = asyncio.run(
        export_backup(
            source, tmp_path / "source", tmp_path / "backups", source_revision="f" * 40
        )
    )
    bundle = tmp_path / "backups" / exported.manifest_digest
    manifest = _verify_bundle(bundle, exported.manifest_digest)
    with target_pin(target, manifest, tmp_path / "pin.json") as pin:
        auth = RecoveryAuthorizationV1.model_validate_json(pin.read_bytes())
        if damage == "missing":
            pin.unlink()
        elif damage == "mode":
            pin.chmod(0o644)
        elif damage == "symlink":
            destination = pin.with_suffix(".private")
            pin.rename(destination)
            pin.symlink_to(destination)
        elif damage == "size":
            pin.write_bytes(b" " * 16_385)
        elif damage == "uid":
            monkeypatch.setattr(recovery.os, "geteuid", lambda: os.getuid() + 1)
        else:
            updates = {}
            if damage == "target":
                updates["expected_target"] = auth.expected_target.model_copy(
                    update={"database_oid": auth.expected_target.database_oid + 1}
                )
            elif damage == "source":
                updates["source_origin_id"] = str(uuid4())
            elif damage == "digest":
                updates["manifest_digest"] = "0" * 64
            elif damage == "runtime_owner":

                async def owner_name():
                    connection = await _connect(target)
                    try:
                        return await connection.fetchval("SELECT session_user")
                    finally:
                        await connection.close()

                updates["runtime_role"] = asyncio.run(owner_name())
            elif damage == "runtime_missing":
                updates["runtime_role"] = "issue532_absent_" + uuid4().hex
            pin.write_bytes(canonical_bytes(auth.model_copy(update=updates)))
        with pytest.raises((RecoveryError, OSError)):
            asyncio.run(
                restore_backup(
                    target,
                    tmp_path / "target",
                    bundle,
                    manifest_digest=manifest.digest,
                    authorization_path=pin,
                )
            )

        async def check():
            connection = await _connect(target)
            try:
                if await connection.fetchval(
                    "SELECT to_regclass('fundamental.fiscal_history_restore_links')"
                ):
                    assert (
                        await connection.fetchval(
                            "SELECT count(*) FROM fundamental.fiscal_history_restore_links"
                        )
                        == 0
                    )
            finally:
                await connection.close()

        asyncio.run(check())


@pytest.mark.parametrize(
    "damage", ["content", "artifact_media", "artifact_dependencies"]
)
def test_completed_retry_refuses_corrupted_current_graph(databases, tmp_path, damage):
    source, target, _ = databases
    bundle, manifest = _seed_backup(source, tmp_path)
    with target_pin(target, manifest, tmp_path / "pin.json") as pin:
        asyncio.run(
            restore_backup(
                target,
                tmp_path / "target",
                bundle,
                manifest_digest=manifest.digest,
                authorization_path=pin,
            )
        )
        if damage == "content":
            item = manifest.objects[0]
            (tmp_path / "target" / item.path.removeprefix("content/")).write_bytes(
                b"corrupt"
            )
        else:

            async def corrupt():
                connection = await _connect(target)
                try:
                    if damage == "artifact_media":
                        await connection.execute(
                            "UPDATE fundamental.artifact_references SET media_type='application/octet-stream'"
                        )
                    else:
                        await connection.execute(
                            "UPDATE fundamental.artifact_references SET dependency_hashes='[\"synthetic:unbound\"]'::jsonb"
                        )
                finally:
                    await connection.close()

            asyncio.run(corrupt())
        with pytest.raises(RecoveryError):
            asyncio.run(
                restore_backup(
                    target,
                    tmp_path / "target",
                    bundle,
                    manifest_digest=manifest.digest,
                    authorization_path=pin,
                )
            )


def test_history_verifier_refuses_broken_seal_head_and_origin_closure(
    databases, tmp_path
):
    from copy import deepcopy
    from fundamental_service.fiscal_history_backup import verify_fiscal_history_backup
    from fundamental_service.persistence_recovery import _backup_tables

    source, _, _ = databases
    bundle, manifest = _seed_backup(source, tmp_path)
    original = _backup_tables(bundle, manifest)
    variants = []
    missing_receipt = deepcopy(original)
    missing_receipt["fiscal_history_commit_receipts"].clear()
    variants.append(missing_receipt)
    wrong_receipt = deepcopy(original)
    wrong_receipt["fiscal_history_commit_receipts"][0]["visible_by"] = (
        "2000-01-01T00:00:00+00:00"
    )
    variants.append(wrong_receipt)
    wrong_head = deepcopy(original)
    wrong_head["fiscal_history_streams"][0]["event_digest"] = "0" * 64
    variants.append(wrong_head)
    wrong_payload = deepcopy(original)
    wrong_payload["fiscal_history_events"][0]["payload_bytes"] += "20"
    variants.append(wrong_payload)
    duplicate_event = deepcopy(original)
    duplicate_event["fiscal_history_events"].append(
        duplicate_event["fiscal_history_events"][0]
    )
    variants.append(duplicate_event)
    unrelated_origin = deepcopy(original)
    unrelated_origin["fiscal_history_origin"].append(
        {**unrelated_origin["fiscal_history_origin"][0], "origin_id": str(uuid4())}
    )
    variants.append(unrelated_origin)
    for changed in variants:
        with pytest.raises(ValueError):
            verify_fiscal_history_backup(changed, manifest.history_frontier)


def test_streaming_copy_uses_original_absolute_deadline_and_publishes_no_bundle(
    databases, tmp_path, monkeypatch
):
    import time
    from fundamental_service import persistence_recovery as recovery

    source, _, _ = databases
    metadata, _ = store(source, tmp_path / "source")
    PostgresContentStore(tmp_path / "source", metadata).put(
        b"synthetic" * 131072, media_type="application/octet-stream"
    )
    metadata.close()

    def slow_storage(source_handle, target_handle):
        while chunk := source_handle.read(32768):
            recovery._check_budget()
            target_handle.write(chunk)
            time.sleep(0.04)

    monkeypatch.setattr(recovery, "_copy_file", slow_storage)
    with pytest.raises(RecoveryError, match="deadline"):
        asyncio.run(
            export_backup(
                source,
                tmp_path / "source",
                tmp_path / "backups",
                source_revision="f" * 40,
                deadline_at=datetime.now(UTC) + timedelta(seconds=0.6),
            )
        )
    assert list((tmp_path / "backups").iterdir()) == []


def _read_pacing(url):
    async def read():
        connection = await _connect(url)
        try:
            return await connection.fetchval(
                "SELECT next_request_at FROM fundamental.sec_provider_rate_limits WHERE rate_key='sec-edgar'"
            )
        finally:
            await connection.close()

    return asyncio.run(read())


def test_completed_retry_preserves_formal_sec_pacing_update(databases, tmp_path):
    source, target, _ = databases
    metadata, _ = store(source, tmp_path / "source")
    metadata.reserve_sec_provider_request_slot(0)
    metadata.close()
    original_slot = _read_pacing(source)
    exported = asyncio.run(
        export_backup(
            source, tmp_path / "source", tmp_path / "backups", source_revision="f" * 40
        )
    )
    bundle = tmp_path / "backups" / exported.manifest_digest
    manifest = _verify_bundle(bundle, exported.manifest_digest)
    with target_pin(target, manifest, tmp_path / "pin.json") as pin:
        initial = asyncio.run(
            restore_backup(
                target,
                tmp_path / "target",
                bundle,
                manifest_digest=manifest.digest,
                authorization_path=pin,
            )
        )
        current, _ = store(target, tmp_path / "target")
        current.reserve_sec_provider_request_slot(0)
        current.close()
        advanced_slot = _read_pacing(target)
        assert advanced_slot > original_slot
        retried = asyncio.run(
            restore_backup(
                target,
                tmp_path / "target",
                bundle,
                manifest_digest=manifest.digest,
                authorization_path=pin,
            )
        )
        assert not retried.wrote and retried.operation_id == initial.operation_id
        assert _read_pacing(target) == advanced_slot


def _release_backup(source, tmp_path):
    from test_postgres_metadata import (
        _activation_command,
        _data_release_candidate,
        _release_test_trust_roots,
    )

    metadata = PostgresMetadataStore(
        source, auto_migrate=True, data_release_trust_roots=_release_test_trust_roots()
    )
    metadata.start()
    (tmp_path / "source").mkdir()
    first, verification = _data_release_candidate(uuid4().hex)
    metadata.publish_data_release_candidate(first, verification)
    initial_pointer = metadata.compare_and_swap_data_release(_activation_command(first))
    metadata.close()
    exported = asyncio.run(
        export_backup(
            source, tmp_path / "source", tmp_path / "backups", source_revision="f" * 40
        )
    )
    bundle = tmp_path / "backups" / exported.manifest_digest
    return (
        bundle,
        _verify_bundle(bundle, exported.manifest_digest),
        first,
        initial_pointer,
    )


def _advance_release(target, tmp_path, first, initial_pointer, *, rollback=False):
    from test_postgres_metadata import (
        _activation_command,
        _data_release_candidate,
        _release_test_trust_roots,
    )

    current = PostgresMetadataStore(
        target, data_release_trust_roots=_release_test_trust_roots()
    )
    current.start()
    second, verification = _data_release_candidate(
        uuid4().hex, profile_id=first.profile_id
    )
    current.publish_data_release_candidate(second, verification)
    pointer = current.compare_and_swap_data_release(
        _activation_command(
            second,
            expected_revision=initial_pointer.revision,
            expected_manifest_digest=first.manifest_digest,
        )
    )
    if rollback:
        pointer = current.compare_and_swap_data_release(
            _activation_command(
                first,
                expected_revision=pointer.revision,
                expected_manifest_digest=second.manifest_digest,
                operation="rollback",
            )
        )
    current.close()
    return second, pointer


@pytest.mark.parametrize("rollback", [False, True])
def test_completed_retry_preserves_formal_release_activation_and_rollback(
    databases, tmp_path, rollback
):
    from test_postgres_metadata import _release_test_trust_roots

    source, target, _ = databases
    bundle, manifest, first, original_pointer = _release_backup(source, tmp_path)
    with target_pin(target, manifest, tmp_path / "pin.json") as pin:
        initial = asyncio.run(
            restore_backup(
                target,
                tmp_path / "target",
                bundle,
                manifest_digest=manifest.digest,
                authorization_path=pin,
            )
        )
        second, latest_pointer = _advance_release(
            target, tmp_path, first, original_pointer, rollback=rollback
        )
        retried = asyncio.run(
            restore_backup(
                target,
                tmp_path / "target",
                bundle,
                manifest_digest=manifest.digest,
                authorization_path=pin,
            )
        )
        assert not retried.wrote and retried.operation_id == initial.operation_id
        reopened = PostgresMetadataStore(
            target, data_release_trust_roots=_release_test_trust_roots()
        )
        reopened.start()
        try:
            assert reopened.get_active_data_release(first.profile_id) == latest_pointer
            assert (
                latest_pointer.manifest_digest
                == (first if rollback else second).manifest_digest
            )
            assert reopened.get_data_release_manifest(first.manifest_digest) == first
            assert reopened.get_data_release_manifest(second.manifest_digest) == second
        finally:
            reopened.close()


@pytest.mark.parametrize(
    "damage",
    [
        "unlogged_target",
        "revision_gap",
        "activated_at",
        "wrong_profile",
        "audit_from",
        "invalid_rollback",
        "old_manifest",
        "old_verification",
        "old_audit",
    ],
)
def test_retry_refuses_invalid_release_pointer_or_changed_immutable_release_prefix(
    databases, tmp_path, damage
):
    from test_postgres_metadata import (
        _data_release_candidate,
        _release_test_trust_roots,
    )

    source, target, _ = databases
    bundle, manifest, first, original_pointer = _release_backup(source, tmp_path)
    with target_pin(target, manifest, tmp_path / "pin.json") as pin:
        asyncio.run(
            restore_backup(
                target,
                tmp_path / "target",
                bundle,
                manifest_digest=manifest.digest,
                authorization_path=pin,
            )
        )
        _advance_release(target, tmp_path, first, original_pointer)
        other, verification = _data_release_candidate(uuid4().hex)
        metadata = PostgresMetadataStore(
            target, data_release_trust_roots=_release_test_trust_roots()
        )
        metadata.start()
        metadata.publish_data_release_candidate(other, verification)
        metadata.close()

        async def corrupt():
            connection = await _connect(target)
            try:
                if damage == "unlogged_target":
                    await connection.execute(
                        "UPDATE fundamental.active_data_release_pointers SET manifest_digest=$1 WHERE profile_id=$2",
                        first.manifest_digest,
                        first.profile_id,
                    )
                elif damage == "revision_gap":
                    await connection.execute(
                        "UPDATE fundamental.active_data_release_pointers SET revision=revision+1"
                    )
                elif damage == "activated_at":
                    await connection.execute(
                        "UPDATE fundamental.active_data_release_pointers SET activated_at=activated_at+interval '1 second'"
                    )
                elif damage == "wrong_profile":
                    await connection.execute(
                        "UPDATE fundamental.active_data_release_pointers SET manifest_digest=$1",
                        other.manifest_digest,
                    )
                elif damage == "audit_from":
                    await connection.execute(
                        "UPDATE fundamental.data_release_activation_audit SET from_manifest_digest=NULL WHERE resulting_revision=2"
                    )
                elif damage == "invalid_rollback":
                    await connection.execute(
                        "UPDATE fundamental.data_release_activation_audit SET operation='rollback' WHERE resulting_revision=2"
                    )
                elif damage == "old_manifest":
                    await connection.execute(
                        "UPDATE fundamental.data_release_manifests SET payload=jsonb_set(payload,'{release_id}','\"corrupt\"'::jsonb) WHERE manifest_digest=$1",
                        first.manifest_digest,
                    )
                elif damage == "old_verification":
                    await connection.execute(
                        "UPDATE fundamental.data_release_verifications SET payload=jsonb_set(payload,'{signature}',to_jsonb(repeat('0',128))) WHERE manifest_digest=$1",
                        first.manifest_digest,
                    )
                else:
                    await connection.execute(
                        "UPDATE fundamental.data_release_activation_audit SET actor_id='corrupt' WHERE resulting_revision=1"
                    )
            finally:
                await connection.close()

        asyncio.run(corrupt())
        with pytest.raises(RecoveryError):
            asyncio.run(
                restore_backup(
                    target,
                    tmp_path / "target",
                    bundle,
                    manifest_digest=manifest.digest,
                    authorization_path=pin,
                )
            )


@pytest.mark.parametrize("damage", ["backwards", "foreign_key"])
def test_retry_refuses_invalid_sec_pacing_state(databases, tmp_path, damage):
    source, target, _ = databases
    metadata, _ = store(source, tmp_path / "source")
    metadata.reserve_sec_provider_request_slot(0)
    metadata.close()
    exported = asyncio.run(
        export_backup(
            source, tmp_path / "source", tmp_path / "backups", source_revision="f" * 40
        )
    )
    bundle = tmp_path / "backups" / exported.manifest_digest
    manifest = _verify_bundle(bundle, exported.manifest_digest)
    with target_pin(target, manifest, tmp_path / "pin.json") as pin:
        asyncio.run(
            restore_backup(
                target,
                tmp_path / "target",
                bundle,
                manifest_digest=manifest.digest,
                authorization_path=pin,
            )
        )

        async def corrupt():
            connection = await _connect(target)
            try:
                if damage == "backwards":
                    await connection.execute(
                        "UPDATE fundamental.sec_provider_rate_limits SET next_request_at=next_request_at-interval '1 second'"
                    )
                else:
                    await connection.execute(
                        "INSERT INTO fundamental.sec_provider_rate_limits VALUES('synthetic:unowned',clock_timestamp())"
                    )
            finally:
                await connection.close()

        asyncio.run(corrupt())
        with pytest.raises(RecoveryError):
            asyncio.run(
                restore_backup(
                    target,
                    tmp_path / "target",
                    bundle,
                    manifest_digest=manifest.digest,
                    authorization_path=pin,
                )
            )


def test_retry_preserves_revalidated_parser_cache_replacement_and_refuses_wrong_result(
    databases, tmp_path
):
    from fundamental_service.parser_action_contracts import ParserActionResultV1
    from test_parser_actions import case

    source, target, _ = databases
    synthetic = case(tmp_path / "synthetic-parser")

    def publish(metadata, artifacts):
        report = synthetic.execute().model_dump(mode="json")
        report_hash = sha256_digest(report)
        artifacts.put_with_receipt(f"sec-parser-action-report-v1:{report_hash}", report)
        result = ParserActionResultV1(
            request=synthetic.request, report_content_hash=report_hash
        )
        artifacts.put_with_receipt(result.artifact_id, result.model_dump(mode="json"))
        metadata.publish_parser_action_result(
            synthetic.request.digest, result.artifact_id
        )
        return result.artifact_id

    metadata, artifacts = store(source, tmp_path / "source")
    original_result = publish(metadata, artifacts)
    metadata.close()
    exported = asyncio.run(
        export_backup(
            source, tmp_path / "source", tmp_path / "backups", source_revision="f" * 40
        )
    )
    bundle = tmp_path / "backups" / exported.manifest_digest
    manifest = _verify_bundle(bundle, exported.manifest_digest)
    with target_pin(target, manifest, tmp_path / "pin.json") as pin:
        initial = asyncio.run(
            restore_backup(
                target,
                tmp_path / "target",
                bundle,
                manifest_digest=manifest.digest,
                authorization_path=pin,
            )
        )
        current, artifacts = store(target, tmp_path / "target")
        replacement = publish(current, artifacts)
        assert replacement != original_result
        current.close()
        retried = asyncio.run(
            restore_backup(
                target,
                tmp_path / "target",
                bundle,
                manifest_digest=manifest.digest,
                authorization_path=pin,
            )
        )
        assert not retried.wrote and retried.operation_id == initial.operation_id
        current, artifacts = store(target, tmp_path / "target")
        try:
            assert current.parser_action_result(synthetic.request.digest) == replacement
            assert artifacts.get(original_result).artifact_id == original_result
            wrong = artifacts.put_with_receipt(
                "synthetic:wrong-parser-result", {"synthetic": True}
            ).artifact
            current.publish_parser_action_result(
                synthetic.request.digest, wrong.artifact_id
            )
        finally:
            current.close()
        with pytest.raises(RecoveryError, match="parser action"):
            asyncio.run(
                restore_backup(
                    target,
                    tmp_path / "target",
                    bundle,
                    manifest_digest=manifest.digest,
                    authorization_path=pin,
                )
            )
