from __future__ import annotations

import asyncio
import os
from contextlib import contextmanager
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql.elements import TextClause

from fundamental_service.data_releases import ArtifactRefV1
from fundamental_service.fiscal_admission_history import (
    FiscalControlBindingV1,
    FiscalCommitPendingV1,
    FiscalCommitReceiptV1,
    PostgresFiscalAdmissionHistory,
)
from fundamental_service.metadata import (
    PostgresArtifactStore,
    PostgresContentStore,
    PostgresMetadataStore,
)
from fundamental_service.snapshots import SnapshotError
from fundamental_service.serialization import canonical_bytes, sha256_digest

DATABASE_URL = os.getenv("FUNDAMENTAL_TEST_DATABASE_URL")
TRACKING_OFF_DATABASE_URL = os.getenv("FUNDAMENTAL_TEST_TRACKING_OFF_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="requires PostgreSQL history storage"
)


def _deadline() -> datetime:
    return datetime.now(UTC) + timedelta(seconds=10)


@pytest.fixture
def database_url() -> Iterator[str]:
    assert DATABASE_URL is not None
    with _temporary_database(DATABASE_URL) as url:
        yield url


@contextmanager
def _temporary_database(url: str) -> Iterator[str]:
    root_url = make_url(url).set(drivername="postgresql")
    name = "issue521_history_" + uuid4().hex

    async def create() -> None:
        connection = await asyncpg.connect(
            root_url.render_as_string(hide_password=False)
        )
        try:
            await connection.execute(f'CREATE DATABASE "{name}"')
        finally:
            await connection.close()

    async def remove() -> None:
        connection = await asyncpg.connect(
            root_url.render_as_string(hide_password=False)
        )
        try:
            await connection.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        finally:
            await connection.close()

    asyncio.run(create())
    try:
        yield root_url.set(database=name).render_as_string(hide_password=False)
    finally:
        asyncio.run(remove())


@pytest.fixture
def metadata(database_url: str) -> Iterator[PostgresMetadataStore]:
    store = PostgresMetadataStore(database_url, auto_migrate=True)
    try:
        store.start()
        yield store
    finally:
        store.close()


@pytest.fixture
def artifacts(metadata: PostgresMetadataStore, tmp_path: Path) -> PostgresArtifactStore:
    return PostgresArtifactStore(metadata, PostgresContentStore(tmp_path, metadata))


def _command(
    artifacts: PostgresArtifactStore, *, suffix: str = "one"
) -> FiscalControlBindingV1:
    record = artifacts.put_with_receipt(
        "synthetic-authority:" + suffix, {"synthetic": True}
    ).artifact
    return FiscalControlBindingV1(
        action="authority_granted",
        command_digest=("a" if suffix == "one" else "b") * 64,
        payload_ref=ArtifactRefV1(
            role="synthetic-fiscal-authority",
            artifact_id=record.artifact_id,
            content_hash=record.content_hash,
            media_type=record.media_type,
        ),
    )


def test_control_append_read_and_retry_are_immutable(metadata, artifacts):
    history = PostgresFiscalAdmissionHistory(metadata)
    command = _command(artifacts)
    first = history.append_once(
        "synthetic-principal", command, expected_head=None, deadline_at=_deadline()
    )
    repeated = history.append_once(
        "synthetic-principal", command, expected_head=None, deadline_at=_deadline()
    )
    assert first.wrote and not repeated.wrote
    assert first.entry == repeated.entry
    read = history.read(("control:synthetic-principal",), deadline_at=_deadline())
    assert read.entries == (first.entry,)
    assert read.heads[0].event_digest == first.entry.event_digest
    history.require_heads(read.heads, deadline_at=_deadline())


def test_checkpoint_tracks_update_and_delete_in_same_metadata_transaction(
    metadata, artifacts
):
    history = PostgresFiscalAdmissionHistory(metadata)
    record = artifacts.put_with_receipt(
        "synthetic-source", {"synthetic": "source"}, ("c" * 64,)
    ).artifact
    first = history.checkpoint((record,), deadline_at=_deadline())

    async def change(connection):
        await connection.execute(
            text(
                "UPDATE fundamental.artifact_references SET status='invalidated' WHERE artifact_id='synthetic-source'"
            )
        )

    metadata.run_fiscal_admission_history(change)
    changed = history.seal_pending(
        ("evidence:synthetic-source",), deadline_at=_deadline()
    )
    assert len(changed.entries) == 2
    assert (
        changed.evidence_as_of(record.artifact_id, at=first.observed_through) == record
    )
    assert (
        changed.evidence_as_of(record.artifact_id, at=changed.observed_through).status
        == "invalidated"
    )

    async def delete(connection):
        await connection.execute(
            text(
                "DELETE FROM fundamental.artifact_references WHERE artifact_id='synthetic-source'"
            )
        )

    metadata.run_fiscal_admission_history(delete)
    deleted = history.seal_pending(
        ("evidence:synthetic-source",), deadline_at=_deadline()
    )
    assert len(deleted.entries) == 3
    assert (
        deleted.evidence_as_of(record.artifact_id, at=deleted.observed_through) is None
    )


def test_same_command_is_deduplicated_across_concurrent_connections(
    metadata, artifacts
):
    history = PostgresFiscalAdmissionHistory(metadata)
    command = _command(artifacts)
    barrier = Barrier(2)

    def append():
        barrier.wait(timeout=5)
        return history.append_once(
            "concurrent", command, expected_head=None, deadline_at=_deadline()
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(append) for _ in range(2)]
        results = [future.result(timeout=10) for future in futures]
    assert sorted(r.wrote for r in results) == [False, True]
    assert results[0].entry == results[1].entry
    assert (
        len(history.read(("control:concurrent",), deadline_at=_deadline()).entries) == 1
    )


def test_concurrent_different_commands_cannot_both_replace_the_same_head(
    metadata, artifacts
):
    history = PostgresFiscalAdmissionHistory(metadata)
    commands = (_command(artifacts), _command(artifacts, suffix="two"))
    barrier = Barrier(2)

    def append(command):
        barrier.wait(timeout=5)
        try:
            return history.append_once(
                "competing", command, expected_head=None, deadline_at=_deadline()
            ).wrote
        except SnapshotError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(append, commands))
    assert True in results and "FISCAL_HISTORY_HEAD_CHANGED" in results
    assert (
        len(history.read(("control:competing",), deadline_at=_deadline()).entries) == 1
    )


def test_control_scope_payload_and_command_reuse_fail_closed(metadata, artifacts):
    history = PostgresFiscalAdmissionHistory(metadata)
    command = _command(artifacts)
    history.append_once(
        "principal", command, expected_head=None, deadline_at=_deadline()
    )
    read = history.read(("control:principal",), deadline_at=_deadline())
    changed_command = command.model_copy(update={"action": "authority_revoked"})
    with pytest.raises(SnapshotError, match="immutable") as failure:
        history.append_once(
            "principal", changed_command, expected_head=None, deadline_at=_deadline()
        )
    assert failure.value.code == "FISCAL_HISTORY_COMMAND_REUSED"
    command2 = _command(artifacts, suffix="two")
    with pytest.raises(SnapshotError) as stale:
        history.append_once(
            "principal", command2, expected_head=None, deadline_at=_deadline()
        )
    assert stale.value.code == "FISCAL_HISTORY_HEAD_CHANGED"
    next_event = history.append_once(
        "principal", command2, expected_head=read.heads[0], deadline_at=_deadline()
    )
    assert next_event.entry.event.sequence == 2
    with pytest.raises(SnapshotError) as changed:
        history.require_heads(read.heads, deadline_at=_deadline())
    assert changed.value.code == "FISCAL_HISTORY_HEAD_CHANGED"
    before = history.read(("control:principal",), deadline_at=_deadline())
    bad_ref = command.payload_ref.model_copy(update={"content_hash": "e" * 64})
    with pytest.raises(SnapshotError):
        history.append_once(
            "other",
            command.model_copy(update={"payload_ref": bad_ref}),
            expected_head=None,
            deadline_at=_deadline(),
        )
    assert (
        history.read(("control:principal",), deadline_at=_deadline()).entries
        == before.entries
    )


def test_checkpoint_is_exact_idempotent_and_has_no_invented_past(metadata, artifacts):
    history = PostgresFiscalAdmissionHistory(metadata)
    record = artifacts.put_with_receipt("source", {"source": 1}).artifact
    first = history.checkpoint((record,), deadline_at=_deadline())
    second = history.checkpoint((record,), deadline_at=_deadline())
    assert second.entries == first.entries
    with pytest.raises(SnapshotError, match="cover"):
        second.evidence_as_of(
            "source", at=first.entries[0].event.recorded_at - timedelta(microseconds=1)
        )
    with pytest.raises(SnapshotError, match="cover"):
        second.evidence_as_of(
            "source", at=second.observed_through + timedelta(seconds=1)
        )
    with pytest.raises(SnapshotError, match="differs"):
        history.checkpoint(
            (record.model_copy(update={"status": "invalidated"}),),
            deadline_at=_deadline(),
        )
    with pytest.raises(SnapshotError, match="unavailable"):
        history.read(("evidence:unknown",), deadline_at=_deadline())
    assert (
        history.read(("evidence:source",), deadline_at=_deadline()).entries
        == first.entries
    )


@pytest.mark.parametrize("limit", ["entries", "bytes"])
def test_read_refuses_a_history_exceeding_its_bound(metadata, artifacts, limit):
    history = PostgresFiscalAdmissionHistory(metadata)
    first = history.append_once(
        "bounded", _command(artifacts), expected_head=None, deadline_at=_deadline()
    )
    head = history.read(("control:bounded",), deadline_at=_deadline()).heads[0]
    history.append_once(
        "bounded",
        _command(artifacts, suffix="two"),
        expected_head=head,
        deadline_at=_deadline(),
    )
    bounded = PostgresFiscalAdmissionHistory(
        metadata,
        **(
            {"max_entries": 1}
            if limit == "entries"
            else {"max_bytes": len(first.entry.payload_bytes) - 1}
        ),
    )
    with pytest.raises(SnapshotError, match="limit"):
        bounded.read(("control:bounded",), deadline_at=_deadline())


def test_metadata_and_history_rollback_together(metadata, artifacts):
    history = PostgresFiscalAdmissionHistory(metadata)
    record = artifacts.put_with_receipt("rollback-source", {}).artifact
    before = history.checkpoint((record,), deadline_at=_deadline())

    async def fail(connection):
        await connection.execute(
            text(
                "UPDATE fundamental.artifact_references SET status='invalidated' WHERE artifact_id='rollback-source'"
            )
        )
        raise RuntimeError("synthetic transaction failure")

    with pytest.raises(RuntimeError, match="synthetic"):
        metadata.run_fiscal_admission_history(fail)
    assert artifacts.get(record.artifact_id) == record
    assert (
        history.read(("evidence:rollback-source",), deadline_at=_deadline()).entries
        == before.entries
    )


@pytest.mark.parametrize("target", ["events", "head", "truncate", "evidence_identity"])
def test_database_rejects_mutating_history_or_registered_identity(
    metadata, artifacts, target
):
    history = PostgresFiscalAdmissionHistory(metadata)
    record = artifacts.put_with_receipt("protected-source", {}).artifact
    before = history.checkpoint((record,), deadline_at=_deadline())
    statements = {
        "events": "DELETE FROM fundamental.fiscal_history_events",
        "head": "UPDATE fundamental.fiscal_history_streams SET sequence=sequence+1",
        "truncate": "TRUNCATE fundamental.artifact_references",
        "evidence_identity": "UPDATE fundamental.artifact_references SET artifact_id='new-source' WHERE artifact_id='protected-source'",
    }

    async def mutate(connection):
        await connection.execute(text(statements[target]))

    with pytest.raises(DBAPIError):
        metadata.run_fiscal_admission_history(mutate)
    assert (
        history.read(("evidence:protected-source",), deadline_at=_deadline()).entries
        == before.entries
    )


def test_migrations_can_repeat_without_rewriting_history(metadata, artifacts):
    history = PostgresFiscalAdmissionHistory(metadata)
    history.append_once(
        "repeat-startup",
        _command(artifacts),
        expected_head=None,
        deadline_at=_deadline(),
    )
    before = history.read(("control:repeat-startup",), deadline_at=_deadline())
    metadata.start()
    assert (
        history.read(("control:repeat-startup",), deadline_at=_deadline()).entries
        == before.entries
    )


def test_failed_multistatement_migration_rolls_back_its_ddl(
    metadata, database_url, monkeypatch, tmp_path
):
    migration = tmp_path / "005_failed.sql"
    migration.write_text(
        "CREATE TABLE fundamental.synthetic_failed_migration(id integer); SELECT 1 / 0;"
    )
    import fundamental_service.metadata as module

    class MigrationRoot:
        def joinpath(self, name):
            return tmp_path

    monkeypatch.setattr(module.resources, "files", lambda _name: MigrationRoot())
    with pytest.raises(SnapshotError) as failure:
        metadata.start()
    assert failure.value.code == "METADATA_SCHEMA_UNAVAILABLE"

    async def exists():
        connection = await asyncpg.connect(database_url)
        try:
            return await connection.fetchval(
                "SELECT to_regclass('fundamental.synthetic_failed_migration')"
            )
        finally:
            await connection.close()

    assert asyncio.run(exists()) is None


@pytest.mark.parametrize("operation", ["append", "read", "checkpoint"])
def test_original_deadline_cancels_a_real_database_lock_wait(
    metadata, artifacts, database_url, operation
):
    history = PostgresFiscalAdmissionHistory(metadata)
    command = _command(artifacts)
    record = artifacts.get(command.payload_ref.artifact_id)
    history.append_once("locked", command, expected_head=None, deadline_at=_deadline())

    async def blocked():
        connection = await asyncpg.connect(database_url)
        try:
            async with connection.transaction():
                if operation == "append":
                    await connection.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended('control:locked', 0))"
                    )
                elif operation == "read":
                    await connection.execute(
                        "LOCK TABLE fundamental.fiscal_history_events IN ACCESS EXCLUSIVE MODE"
                    )
                else:
                    await connection.execute(
                        "SELECT 1 FROM fundamental.artifact_references WHERE artifact_id=$1 FOR UPDATE",
                        record.artifact_id,
                    )

                def invoke():
                    deadline = datetime.now(UTC) + timedelta(seconds=0.2)
                    if operation == "append":
                        next_command = command.model_copy(
                            update={"command_digest": "b" * 64}
                        )
                        head = history.read(
                            ("control:locked",), deadline_at=_deadline()
                        ).heads[0]
                        return history.append_once(
                            "locked",
                            next_command,
                            expected_head=head,
                            deadline_at=deadline,
                        )
                    if operation == "read":
                        return history.read(("control:locked",), deadline_at=deadline)
                    return history.checkpoint((record,), deadline_at=deadline)

                task = asyncio.create_task(asyncio.to_thread(invoke))
                blocker = connection.get_server_pid()
                async with asyncio.timeout(3):
                    while not await connection.fetchval(
                        "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE $1=ANY(pg_blocking_pids(pid)))",
                        blocker,
                    ):
                        assert not task.done(), (
                            "history returned before its query blocked"
                        )
                        await asyncio.sleep(0.005)
                    with pytest.raises(SnapshotError) as expired:
                        await asyncio.shield(task)
                    assert expired.value.code == "REQUEST_DEADLINE_EXCEEDED"
                    while await connection.fetchval(
                        "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE $1=ANY(pg_blocking_pids(pid)))",
                        blocker,
                    ):
                        await asyncio.sleep(0.005)
        finally:
            await connection.close()

    asyncio.run(blocked())
    assert len(history.read(("control:locked",), deadline_at=_deadline()).entries) == 1


@pytest.mark.parametrize("damage", ["gap", "hash", "scope", "command"])
def test_reader_detects_corrupt_or_incomplete_prefix(metadata, artifacts, damage):
    history = PostgresFiscalAdmissionHistory(metadata)
    first = history.append_once(
        "damaged", _command(artifacts), expected_head=None, deadline_at=_deadline()
    )
    event = first.entry.event.model_copy(
        update={
            "sequence": 3 if damage == "gap" else 2,
            "previous_digest": first.entry.event_digest,
            "subject_id": "other" if damage == "scope" else "damaged",
        }
    )
    raw = canonical_bytes(event)
    digest = "e" * 64 if damage == "hash" else sha256_digest(event)

    async def corrupt(connection):
        await connection.execute(
            text(
                "ALTER TABLE fundamental.fiscal_history_events DISABLE TRIGGER fiscal_history_event_writer_guard"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO fundamental.fiscal_history_events(stream_id, sequence, event_digest, payload_bytes, origin_id, writer_xid8) "
                "VALUES ('control:damaged', 2, :digest, :raw, CAST(:origin AS uuid), CAST(:writer AS xid8))"
            ),
            {
                "digest": digest,
                "raw": raw,
                "origin": event.origin_id,
                "writer": event.writer_xid8,
            },
        )
        await connection.execute(
            text(
                "UPDATE fundamental.fiscal_history_streams SET sequence=2, event_digest=:digest WHERE stream_id='control:damaged'"
            ),
            {"digest": digest},
        )
        await connection.execute(
            text(
                "ALTER TABLE fundamental.fiscal_history_events ENABLE TRIGGER fiscal_history_event_writer_guard"
            )
        )

    metadata.run_fiscal_admission_history(corrupt)
    with pytest.raises(SnapshotError) as failure:
        history.read(("control:damaged",), deadline_at=_deadline())
    assert failure.value.code == "FISCAL_ADMISSION_HISTORY_UNAVAILABLE"


def test_append_failure_rolls_back_event_and_head(metadata, artifacts):
    command = _command(artifacts)
    too_small = PostgresFiscalAdmissionHistory(metadata, max_bytes=1)
    with pytest.raises(SnapshotError, match="limit"):
        too_small.append_once(
            "rollback-control", command, expected_head=None, deadline_at=_deadline()
        )
    history = PostgresFiscalAdmissionHistory(metadata)
    with pytest.raises(SnapshotError, match="unavailable"):
        history.read(("control:rollback-control",), deadline_at=_deadline())
    assert history.append_once(
        "rollback-control", command, expected_head=None, deadline_at=_deadline()
    ).wrote


def test_control_refuses_invalidated_payload(metadata, artifacts):
    history = PostgresFiscalAdmissionHistory(metadata)
    command = _command(artifacts)

    async def invalidate(connection):
        await connection.execute(
            text(
                "UPDATE fundamental.artifact_references SET status='invalidated' WHERE artifact_id=:identity"
            ),
            {"identity": command.payload_ref.artifact_id},
        )

    metadata.run_fiscal_admission_history(invalidate)
    with pytest.raises(SnapshotError, match="valid retained"):
        history.append_once(
            "refused", command, expected_head=None, deadline_at=_deadline()
        )


def test_deleted_registered_evidence_reinsertion_remains_in_the_same_stream(
    metadata, artifacts
):
    history = PostgresFiscalAdmissionHistory(metadata)
    record = artifacts.put_with_receipt("recreated", {}).artifact
    history.checkpoint((record,), deadline_at=_deadline())

    async def replace(connection):
        await connection.execute(
            text(
                "DELETE FROM fundamental.artifact_references WHERE artifact_id='recreated'"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO fundamental.artifact_references "
                "(artifact_id,content_hash,media_type,dependency_hashes,status,retention) "
                "VALUES ('recreated',:hash,'application/json','[]'::jsonb,'valid','evidence')"
            ),
            {"hash": record.content_hash},
        )

    metadata.run_fiscal_admission_history(replace)
    read = history.seal_pending(("evidence:recreated",), deadline_at=_deadline())
    assert len(read.entries) == 3
    assert read.entries[1].event.body.record is None
    assert read.entries[2].event.body.previous_record is None
    assert read.evidence_as_of(record.artifact_id, at=read.observed_through) == record


def test_unrecorded_metadata_change_cannot_fabricate_complete_history(
    metadata, artifacts
):
    history = PostgresFiscalAdmissionHistory(metadata)
    record = artifacts.put_with_receipt("missing-transition", {}).artifact
    history.checkpoint((record,), deadline_at=_deadline())

    async def corrupt(connection):
        await connection.execute(
            text(
                "ALTER TABLE fundamental.artifact_references DISABLE TRIGGER fiscal_capture_artifact_transition"
            )
        )
        await connection.execute(
            text(
                "UPDATE fundamental.artifact_references SET status='invalidated' WHERE artifact_id='missing-transition'"
            )
        )
        await connection.execute(
            text(
                "ALTER TABLE fundamental.artifact_references ENABLE TRIGGER fiscal_capture_artifact_transition"
            )
        )

    metadata.run_fiscal_admission_history(corrupt)
    with pytest.raises(SnapshotError, match="current metadata"):
        history.read(("evidence:missing-transition",), deadline_at=_deadline())


def test_commit_delay_is_ambiguous_and_stable_windows_replay(
    metadata, artifacts, database_url
):
    history = PostgresFiscalAdmissionHistory(metadata)
    record = artifacts.put_with_receipt("commit-delay", {}).artifact
    first = history.checkpoint((record,), deadline_at=_deadline())

    async def change():
        writer = await asyncpg.connect(database_url)
        reader = await asyncpg.connect(database_url)
        try:
            await writer.execute("SET commit_delay=100000")
            await writer.execute("SET commit_siblings=0")
            await writer.execute("SET synchronous_commit=on")
            transaction = writer.transaction()
            await transaction.start()
            await writer.execute(
                "UPDATE fundamental.artifact_references SET status='invalidated' WHERE artifact_id=$1",
                record.artifact_id,
            )
            commit = asyncio.create_task(transaction.commit())
            observations = []
            while not commit.done():
                row = await reader.fetchrow(
                    "SELECT statement_timestamp() AS observed, status FROM fundamental.artifact_references WHERE artifact_id=$1",
                    record.artifact_id,
                )
                if row["status"] == "valid":
                    observations.append(row["observed"])
            await commit
            return observations
        finally:
            await writer.close()
            await reader.close()

    observations = asyncio.run(change())
    read = history.seal_pending(("evidence:commit-delay",), deadline_at=_deadline())
    bound = read.entries[-1].commit_bound
    assert isinstance(bound, FiscalCommitReceiptV1)
    delayed = [t for t in observations if bound.committed_at <= t <= bound.visible_by]
    assert delayed, "the probe must observe an old snapshot after the commit stamp"
    assert read.evidence_as_of(record.artifact_id, at=first.observed_through) == record
    for at in (delayed[-1], bound.committed_at, bound.visible_by):
        with pytest.raises(SnapshotError, match="visibility_ambiguous"):
            read.evidence_as_of(record.artifact_id, at=at)
    assert (
        read.evidence_as_of(record.artifact_id, at=read.observed_through).status
        == "invalidated"
    )


def test_reads_leave_pending_commits_unmodified_until_explicit_seal(
    metadata, artifacts
):
    history = PostgresFiscalAdmissionHistory(metadata)
    record = artifacts.put_with_receipt("pending", {}).artifact
    first = history.checkpoint((record,), deadline_at=_deadline())

    async def invalidate(connection):
        await connection.execute(
            text(
                "UPDATE fundamental.artifact_references SET status='invalidated' WHERE artifact_id='pending'"
            )
        )

    metadata.run_fiscal_admission_history(invalidate)

    async def counts(connection):
        return (
            await connection.execute(
                text(
                    "SELECT (SELECT count(*) FROM fundamental.fiscal_history_events), "
                    "(SELECT count(*) FROM fundamental.fiscal_history_commit_receipts)"
                )
            )
        ).one()

    before = metadata.run_fiscal_admission_history(counts)
    pending = history.read(("evidence:pending",), deadline_at=_deadline())
    again = history.read(("evidence:pending",), deadline_at=_deadline())
    assert before == metadata.run_fiscal_admission_history(counts) == (2, 1)
    assert pending.entries == again.entries
    assert isinstance(pending.entries[-1].commit_bound, FiscalCommitPendingV1)
    assert (
        pending.evidence_as_of(record.artifact_id, at=first.observed_through) == record
    )
    with pytest.raises(SnapshotError, match="visibility_ambiguous"):
        pending.evidence_as_of(record.artifact_id, at=pending.observed_through)
    barrier = Barrier(2)

    def seal():
        barrier.wait(timeout=5)
        return history.seal_pending(("evidence:pending",), deadline_at=_deadline())

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(seal) for _ in range(2)]
        sealed, competing = [future.result(timeout=10) for future in futures]
    assert sealed.entries == competing.entries
    assert (
        sealed.evidence_as_of(record.artifact_id, at=sealed.observed_through).status
        == "invalidated"
    )
    assert sealed.entries[-1].payload_bytes == pending.entries[-1].payload_bytes
    assert metadata.run_fiscal_admission_history(counts) == (2, 2)


def test_one_transaction_is_atomic_across_events_and_streams(metadata, artifacts):
    history = PostgresFiscalAdmissionHistory(metadata)
    records = tuple(
        artifacts.put_with_receipt(name, {}).artifact
        for name in ("atomic-a", "atomic-b")
    )
    streams = tuple("evidence:" + r.artifact_id for r in records)
    first = history.checkpoint(records, deadline_at=_deadline())

    async def change(connection):
        for status in ("invalidated", "valid"):
            await connection.execute(
                text(
                    "UPDATE fundamental.artifact_references SET status=:status WHERE artifact_id IN ('atomic-a','atomic-b')"
                ),
                {"status": status},
            )

    metadata.run_fiscal_admission_history(change)
    read = history.seal_pending(streams, deadline_at=_deadline())
    transitions = [e for e in read.entries if e.event.sequence > 1]
    assert len(transitions) == 4
    assert len({e.event.writer_xid8 for e in transitions}) == 1
    assert len({e.commit_bound for e in transitions}) == 1
    bound = transitions[0].commit_bound
    assert isinstance(bound, FiscalCommitReceiptV1)
    for stream in streams:
        assert len(read.prefix_as_of(stream, at=first.observed_through)) == 1
        with pytest.raises(SnapshotError, match="visibility_ambiguous"):
            read.prefix_as_of(stream, at=bound.committed_at)
        assert len(read.prefix_as_of(stream, at=read.observed_through)) == 3
    with ThreadPoolExecutor(max_workers=2) as pool:
        repeated = list(
            pool.map(
                lambda _: history.seal_pending(streams, deadline_at=_deadline()),
                range(2),
            )
        )
    assert repeated[0].entries == repeated[1].entries == read.entries


def test_second_transaction_deadline_leaves_recoverable_command(
    metadata, artifacts, database_url
):
    history = PostgresFiscalAdmissionHistory(metadata)
    command = _command(artifacts)

    async def blocked():
        blocker = await asyncpg.connect(database_url)
        try:
            async with blocker.transaction():
                await blocker.execute(
                    "LOCK TABLE fundamental.fiscal_history_commit_receipts IN SHARE MODE"
                )
                task = asyncio.create_task(
                    asyncio.to_thread(
                        history.append_once,
                        "seal-deadline",
                        command,
                        expected_head=None,
                        deadline_at=datetime.now(UTC) + timedelta(seconds=0.4),
                    )
                )
                async with asyncio.timeout(3):
                    while not await blocker.fetchval(
                        "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE $1=ANY(pg_blocking_pids(pid)))",
                        blocker.get_server_pid(),
                    ):
                        assert not task.done()
                        await asyncio.sleep(0.005)
                    assert (
                        await blocker.fetchval(
                            "SELECT count(*) FROM fundamental.fiscal_history_events"
                        )
                        == 1
                    )
                    assert (
                        await blocker.fetchval(
                            "SELECT count(*) FROM fundamental.fiscal_history_commit_receipts"
                        )
                        == 0
                    )
                    with pytest.raises(SnapshotError) as failure:
                        await asyncio.shield(task)
                    assert failure.value.code == "REQUEST_DEADLINE_EXCEEDED"
                    while await blocker.fetchval(
                        "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE $1=ANY(pg_blocking_pids(pid)))",
                        blocker.get_server_pid(),
                    ):
                        await asyncio.sleep(0.005)
        finally:
            await blocker.close()

    asyncio.run(blocked())
    pending = history.read(("control:seal-deadline",), deadline_at=_deadline())
    assert isinstance(pending.entries[0].commit_bound, FiscalCommitPendingV1)
    recovered = history.append_once(
        "seal-deadline", command, expected_head=None, deadline_at=_deadline()
    )
    assert not recovered.wrote
    assert isinstance(recovered.entry.commit_bound, FiscalCommitReceiptV1)
    assert recovered.entry.payload_bytes == pending.entries[0].payload_bytes
    assert (
        history.append_once(
            "seal-deadline", command, expected_head=None, deadline_at=_deadline()
        ).entry
        == recovered.entry
    )


def test_seal_rollback_and_lost_ack_recover_without_rewriting(
    metadata, artifacts, monkeypatch
):
    history = PostgresFiscalAdmissionHistory(metadata)
    record = artifacts.put_with_receipt("crash-recovery", {}).artifact
    history.checkpoint((record,), deadline_at=_deadline())

    async def change(connection):
        await connection.execute(
            text(
                "UPDATE fundamental.artifact_references SET status='invalidated' WHERE artifact_id='crash-recovery'"
            )
        )

    metadata.run_fiscal_admission_history(change)
    pending = history.read(("evidence:crash-recovery",), deadline_at=_deadline())
    original = history._seal_pending

    async def interrupted(streams, connection):
        await original(streams, connection)
        raise RuntimeError("synthetic crash before receipt commit")

    with monkeypatch.context() as patch:
        patch.setattr(history, "_seal_pending", interrupted)
        with pytest.raises(RuntimeError, match="synthetic crash"):
            history.seal_pending(("evidence:crash-recovery",), deadline_at=_deadline())
    assert (
        history.read(("evidence:crash-recovery",), deadline_at=_deadline()).entries
        == pending.entries
    )
    sealed = history.seal_pending(("evidence:crash-recovery",), deadline_at=_deadline())
    original_read = history.read

    def lost_ack(*args, **kwargs):
        original_read(*args, **kwargs)
        raise RuntimeError("synthetic lost acknowledgement")

    with monkeypatch.context() as patch:
        patch.setattr(history, "read", lost_ack)
        with pytest.raises(RuntimeError, match="lost acknowledgement"):
            history.seal_pending(("evidence:crash-recovery",), deadline_at=_deadline())
    recovered = history.seal_pending(
        ("evidence:crash-recovery",), deadline_at=_deadline()
    )
    assert recovered.entries == sealed.entries
    assert tuple(e.payload_bytes for e in recovered.entries) == tuple(
        e.payload_bytes for e in pending.entries
    )


@pytest.mark.parametrize(
    "damage", ["time", "origin", "unknown", "update", "delete", "truncate"]
)
def test_receipt_writer_derives_times_and_rejects_tampering(
    metadata, artifacts, damage
):
    history = PostgresFiscalAdmissionHistory(metadata)
    entry = history.append_once(
        "receipt-guard",
        _command(artifacts),
        expected_head=None,
        deadline_at=_deadline(),
    ).entry
    statements = {
        "time": "INSERT INTO fundamental.fiscal_history_commit_receipts(origin_id,writer_xid8,committed_at,visible_by) VALUES (CAST(:origin AS uuid),CAST(:writer AS xid8),'2000-01-01T00:00:00Z','2000-01-02T00:00:00Z')",
        "origin": "SELECT fundamental.fiscal_history_seal('00000000-0000-0000-0000-000000000000',CAST(:writer AS xid8))",
        "unknown": "SELECT fundamental.fiscal_history_seal(CAST(:origin AS uuid),'1'::xid8)",
        "update": "UPDATE fundamental.fiscal_history_commit_receipts SET visible_by=clock_timestamp()",
        "delete": "DELETE FROM fundamental.fiscal_history_commit_receipts",
        "truncate": "TRUNCATE fundamental.fiscal_history_commit_receipts",
    }

    async def mutate(connection):
        await connection.execute(
            text(statements[damage]),
            {"origin": entry.event.origin_id, "writer": entry.event.writer_xid8},
        )

    with pytest.raises(DBAPIError):
        metadata.run_fiscal_admission_history(mutate)
    assert history.read(
        ("control:receipt-guard",), deadline_at=_deadline()
    ).entries == (entry,)


@pytest.mark.parametrize("failure_reason", ["unsafe_xid", "commit_log_missing"])
def test_missing_commit_log_is_fail_closed_but_archived_receipts_survive(
    metadata, artifacts, failure_reason
):
    history = PostgresFiscalAdmissionHistory(metadata)
    record = artifacts.put_with_receipt("log-gap", {}).artifact
    first = history.checkpoint((record,), deadline_at=_deadline())

    async def simulate_lost_log(connection):
        await connection.execute(
            text(
                "CREATE OR REPLACE FUNCTION fundamental.fiscal_history_commit_lower(origin UUID, writer XID8) "
                "RETURNS JSONB LANGUAGE sql AS $body$ SELECT jsonb_build_object('kind','missing','reason', '"
                + failure_reason
                + "') $body$"
            )
        )

    metadata.run_fiscal_admission_history(simulate_lost_log)
    archived = history.read(("evidence:log-gap",), deadline_at=_deadline())
    assert (
        archived.evidence_as_of(record.artifact_id, at=first.observed_through) == record
    )

    async def change(connection):
        await connection.execute(
            text(
                "UPDATE fundamental.artifact_references SET status='invalidated' WHERE artifact_id='log-gap'"
            )
        )

    metadata.run_fiscal_admission_history(change)
    pending = history.read(("evidence:log-gap",), deadline_at=_deadline())
    with pytest.raises(SnapshotError, match="lower bound"):
        pending.evidence_as_of(record.artifact_id, at=first.observed_through)
    with pytest.raises(SnapshotError) as refused:
        history.seal_pending(("evidence:log-gap",), deadline_at=_deadline())
    assert refused.value.code == "FISCAL_ADMISSION_HISTORY_UNAVAILABLE"


def test_real_full_xid_guards_reject_future_epoch_and_reserved_xid(metadata):
    async def check(connection):
        writer = await connection.scalar(text("SELECT pg_current_xact_id()"))
        results = []
        for candidate in (writer + 2**32, writer + 2**31, 1):
            results.append(
                await connection.scalar(
                    text(
                        "SELECT fundamental.fiscal_history_commit_lower(fundamental.fiscal_history_origin_id(), CAST(:writer AS xid8))"
                    ),
                    {"writer": candidate},
                )
            )
        return results

    assert all(
        item == {"kind": "missing", "reason": "unsafe_xid"}
        for item in metadata.run_fiscal_admission_history(check)
    )


@pytest.mark.skipif(
    not TRACKING_OFF_DATABASE_URL,
    reason="requires a PostgreSQL instance with commit tracking disabled",
)
def test_history_write_requires_commit_tracking_on(artifacts):
    assert TRACKING_OFF_DATABASE_URL is not None
    with _temporary_database(TRACKING_OFF_DATABASE_URL) as url:
        store = PostgresMetadataStore(url, auto_migrate=True)
        try:
            store.start()
            content = artifacts.put_with_receipt("tracking-source", {}).artifact

            async def insert(connection):
                assert (
                    await connection.scalar(text("SHOW track_commit_timestamp"))
                    == "off"
                )
                await connection.execute(
                    text(
                        "INSERT INTO fundamental.artifact_references (artifact_id,content_hash,media_type,dependency_hashes,status,retention) "
                        "VALUES (:identity,:hash,'application/json','[]'::jsonb,'valid','evidence')"
                    ),
                    {"identity": content.artifact_id, "hash": content.content_hash},
                )

            store.run_fiscal_admission_history(insert)
            with pytest.raises(SnapshotError) as refused:
                PostgresFiscalAdmissionHistory(store).checkpoint(
                    (content,), deadline_at=_deadline()
                )
            assert refused.value.code == "FISCAL_ADMISSION_HISTORY_UNAVAILABLE"
        finally:
            store.close()


@pytest.mark.parametrize("damage", ["clock", "origin", "writer_column"])
def test_reader_refuses_simulated_clock_origin_and_writer_corruption(
    metadata, artifacts, damage
):
    history = PostgresFiscalAdmissionHistory(metadata)
    history.append_once(
        "corrupt-proof",
        _command(artifacts),
        expected_head=None,
        deadline_at=_deadline(),
    )
    statements = {
        "clock": (
            "ALTER TABLE fundamental.fiscal_history_commit_receipts DISABLE TRIGGER fiscal_history_receipts_immutable",
            "UPDATE fundamental.fiscal_history_commit_receipts SET committed_at='2000-01-01T00:00:00Z', visible_by='2000-01-02T00:00:00Z'",
        ),
        "origin": (
            "ALTER TABLE fundamental.fiscal_history_origin DISABLE TRIGGER fiscal_history_origin_immutable",
            "UPDATE fundamental.fiscal_history_origin SET timeline_id=timeline_id+1",
        ),
        "writer_column": (
            "ALTER TABLE fundamental.fiscal_history_events DISABLE TRIGGER fiscal_history_events_immutable",
            "UPDATE fundamental.fiscal_history_events SET writer_xid8='1'::xid8",
        ),
    }

    async def corrupt(connection):
        for sql in statements[damage]:
            await connection.execute(text(sql))

    metadata.run_fiscal_admission_history(corrupt)
    with pytest.raises(SnapshotError) as refused:
        history.read(("control:corrupt-proof",), deadline_at=_deadline())
    assert refused.value.code == "FISCAL_ADMISSION_HISTORY_UNAVAILABLE"


def test_archived_receipts_replay_after_real_vacuum_freeze(
    metadata, artifacts, database_url
):
    history = PostgresFiscalAdmissionHistory(metadata)
    record = artifacts.put_with_receipt("frozen", {}).artifact
    before = history.checkpoint((record,), deadline_at=_deadline())

    async def freeze():
        connection = await asyncpg.connect(database_url)
        try:
            await connection.execute("VACUUM FREEZE fundamental.fiscal_history_events")
        finally:
            await connection.close()

    asyncio.run(freeze())
    read = history.read(("evidence:frozen",), deadline_at=_deadline())
    assert read.entries == before.entries
    assert read.evidence_as_of(record.artifact_id, at=before.observed_through) == record


def test_event_writer_cannot_reuse_an_old_commit_or_seal_an_uncommitted_event(
    metadata, artifacts
):
    history = PostgresFiscalAdmissionHistory(metadata)
    first = history.append_once(
        "writer-guard", _command(artifacts), expected_head=None, deadline_at=_deadline()
    )

    async def forge(connection):
        await connection.execute(
            text(
                "INSERT INTO fundamental.fiscal_history_events "
                "(stream_id,sequence,event_digest,payload_bytes,origin_id,writer_xid8) "
                "VALUES ('control:writer-guard',2,:digest,:raw,CAST(:origin AS uuid),CAST(:writer AS xid8))"
            ),
            {
                "digest": first.entry.event_digest,
                "raw": first.entry.payload_bytes,
                "origin": first.entry.event.origin_id,
                "writer": first.entry.event.writer_xid8,
            },
        )

    with pytest.raises(DBAPIError):
        metadata.run_fiscal_admission_history(forge)

    async def premature(connection):
        await connection.execute(
            text(
                "SELECT fundamental.fiscal_history_append('control:premature','control','premature',CAST(:body AS jsonb),:command)"
            ),
            {
                "body": canonical_bytes(first.entry.event.body).decode(),
                "command": first.entry.event.body.command_digest,
            },
        )
        await connection.execute(
            text(
                "SELECT fundamental.fiscal_history_seal(fundamental.fiscal_history_origin_id(), pg_current_xact_id())"
            )
        )

    with pytest.raises(DBAPIError):
        metadata.run_fiscal_admission_history(premature)
    assert history.read(("control:writer-guard",), deadline_at=_deadline()).entries == (
        first.entry,
    )
    with pytest.raises(SnapshotError):
        history.read(("control:premature",), deadline_at=_deadline())


@pytest.mark.parametrize("operation", ["checkpoint", "append"])
def test_success_rechecks_dependencies_after_the_first_commit(
    metadata, artifacts, monkeypatch, operation
):
    history = PostgresFiscalAdmissionHistory(metadata)
    command = _command(artifacts)
    record = artifacts.get(command.payload_ref.artifact_id)
    original = history.seal_pending

    def invalidate_then_seal(*args, **kwargs):
        async def change(connection):
            await connection.execute(
                text(
                    "UPDATE fundamental.artifact_references SET status='invalidated' WHERE artifact_id=:identity"
                ),
                {"identity": record.artifact_id},
            )

        metadata.run_fiscal_admission_history(change)
        return original(*args, **kwargs)

    monkeypatch.setattr(history, "seal_pending", invalidate_then_seal)
    with pytest.raises(SnapshotError, match="differs"):
        if operation == "checkpoint":
            history.checkpoint((record,), deadline_at=_deadline())
        else:
            history.append_once(
                "dependency-recheck",
                command,
                expected_head=None,
                deadline_at=_deadline(),
            )


class _SimulatedHistoryClock:
    def __init__(self, connection: AsyncConnection, now: datetime) -> None:
        self.connection = connection
        self.now = now

    async def scalar(
        self, statement: TextClause, parameters: dict[str, object] | None = None
    ) -> object:
        if str(statement) == "SELECT clock_timestamp()":
            return self.now
        return await self.connection.scalar(statement, parameters)

    async def execute(
        self, statement: TextClause, parameters: dict[str, object] | None = None
    ) -> object:
        return await self.connection.execute(statement, parameters)


@pytest.mark.parametrize("reverse_clock", [False, True])
def test_uncommitted_event_clock_refuses_reversal_without_inventing_a_commit(
    metadata, artifacts, reverse_clock
):
    history = PostgresFiscalAdmissionHistory(metadata)
    record = artifacts.put_with_receipt("synthetic-pending-clock", {}).artifact
    stream = "evidence:" + record.artifact_id

    async def checkpoint_and_read(connection):
        pending = await history._checkpoint((record,), connection)
        entry = pending.entries[0]
        assert isinstance(entry.commit_bound, FiscalCommitPendingV1)
        assert entry.commit_bound.lower_bound.kind == "missing"
        if reverse_clock:
            now = entry.event.recorded_at - timedelta(microseconds=1)
            return await history._read(
                (stream,),
                _SimulatedHistoryClock(connection, now),
                observed_through=now,
            )
        return pending

    if reverse_clock:
        with pytest.raises(SnapshotError, match="clock"):
            metadata.run_fiscal_admission_history(checkpoint_and_read)
    else:
        read = metadata.run_fiscal_admission_history(checkpoint_and_read)
        with pytest.raises(SnapshotError, match="lower bound"):
            read.evidence_as_of(record.artifact_id, at=read.observed_through)


@pytest.mark.parametrize("phase", ["pending_commit", "sealed_visibility"])
def test_visible_commit_bound_after_simulated_database_now_refuses_read(
    metadata, artifacts, phase
):
    history = PostgresFiscalAdmissionHistory(metadata)
    record = artifacts.put_with_receipt("synthetic-bound-clock", {}).artifact
    stream = "evidence:" + record.artifact_id
    history.checkpoint((record,), deadline_at=_deadline())

    async def invalidate(connection):
        await connection.execute(
            text(
                "UPDATE fundamental.artifact_references SET status='invalidated' WHERE artifact_id=:identity"
            ),
            {"identity": record.artifact_id},
        )

    metadata.run_fiscal_admission_history(invalidate)
    read = (
        history.seal_pending((stream,), deadline_at=_deadline())
        if phase == "sealed_visibility"
        else history.read((stream,), deadline_at=_deadline())
    )
    entry = read.entries[-1]
    bound = entry.commit_bound
    if phase == "sealed_visibility":
        assert isinstance(bound, FiscalCommitReceiptV1)
        now = bound.visible_by - timedelta(microseconds=1)
        assert now > bound.committed_at
    else:
        assert isinstance(bound, FiscalCommitPendingV1)
        assert bound.lower_bound.kind == "known"
        now = bound.lower_bound.committed_at - timedelta(microseconds=1)
    assert now > entry.event.recorded_at

    async def simulated_read(connection):
        await connection.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        )
        return await history._read(
            (stream,),
            _SimulatedHistoryClock(connection, now),
            observed_through=now,
        )

    with pytest.raises(SnapshotError, match="clock"):
        metadata.run_fiscal_admission_history(simulated_read)


def test_snapshot_can_include_events_after_its_transaction_timestamp(
    metadata, artifacts, database_url
):
    history = PostgresFiscalAdmissionHistory(metadata)
    record = artifacts.put_with_receipt("synthetic-late-snapshot", {}).artifact
    stream = "evidence:" + record.artifact_id
    history.checkpoint((record,), deadline_at=_deadline())
    writer = PostgresMetadataStore(database_url, auto_migrate=False)
    writer.start()
    writer_history = PostgresFiscalAdmissionHistory(writer)

    def invalidate_and_seal():
        async def invalidate(connection):
            await connection.execute(
                text(
                    "UPDATE fundamental.artifact_references SET status='invalidated' WHERE artifact_id=:identity"
                ),
                {"identity": record.artifact_id},
            )

        writer.run_fiscal_admission_history(invalidate)
        writer_history.seal_pending((stream,), deadline_at=_deadline())

    async def read_late_snapshot(connection):
        await connection.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        )
        await asyncio.to_thread(invalidate_and_seal)
        observed = await connection.scalar(text("SELECT transaction_timestamp()"))
        return await history._read((stream,), connection, observed_through=observed)

    try:
        read = metadata.run_fiscal_admission_history(read_late_snapshot)
    finally:
        writer.close()
    entry = read.entries[-1]
    assert len(read.entries) == 2
    assert entry.event.recorded_at > read.observed_through
    assert isinstance(entry.commit_bound, FiscalCommitReceiptV1)
    assert entry.commit_bound.visible_by > read.observed_through
    assert entry.event.body.record.status == "invalidated"
    assert read.evidence_as_of(record.artifact_id, at=read.observed_through) == record
