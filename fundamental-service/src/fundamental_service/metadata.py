"""Fundamental-owned PostgreSQL metadata and content-backed repositories.

The domain remains synchronous and stateless per request.  This adapter owns a
small background event loop so repository calls can use SQLAlchemy's async
PostgreSQL engine without leaking async plumbing through the deterministic
calculator or the existing repository protocols.
"""

from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import sys
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Iterator
from concurrent.futures import Future, wait
from contextlib import asynccontextmanager, contextmanager
from contextvars import Context, ContextVar
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from pathlib import Path
from stat import S_ISDIR
from threading import Event, Lock, Thread
from typing import Any, BinaryIO, Literal, TypeVar
from uuid import uuid4

import asyncpg
from sqlalchemy import bindparam, event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from .contracts import (
    CanonicalFactV1,
    IdentityV1,
    ReleaseManifestV1,
    SecIngestionResponseV1,
    SourceSnapshotV1,
)
from .publication_codec import (
    ActivePublication,
    PublicationManifest,
    PublicationVerification,
    active_publication,
    decode_release_manifest,
    decode_release_verification,
    verify_publication_pair,
)
from .fiscal_release_contracts import FiscalReleaseManifestV1
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .fiscal_admission_history import FiscalActivationObservationV1

from .data_releases import (
    DATA_RELEASE_CAPABILITY,
    ActiveDataReleaseV1,
    DataReleaseActivationCommandV1,
    DataReleaseError,
    DataReleaseTrustRootsV1,
)
from .facts import (
    CanonicalFactRepository,
    CanonicalMappingV1,
    canonical_fact_digest,
    resolve_canonical_facts,
)
from .original_issuer import IssuerOperatingSourceV1
from .policies import ModelSpecV1, PolicyRecordV1
from .replay import (
    ArtifactPublicationDeadlineExceeded,
    ArtifactPublicationV1,
    ArtifactRecordV1,
    check_publication_budget,
)
from .serialization import canonical_bytes, sha256_digest
from .snapshots import FilesystemContentStore, SnapshotError, SnapshotRepository

SCHEMA = "fundamental"
SCHEMA_VERSION = "fundamental-metadata-v2"
_T = TypeVar("_T")


@dataclass(frozen=True)
class _MetadataBudget:
    remaining: Callable[[], float]
    expired: Callable[[], SnapshotError]

    def check(self) -> float:
        remaining = self.remaining()
        if remaining <= 0:
            raise self.expired()
        return remaining


_metadata_budget: ContextVar[_MetadataBudget | None] = ContextVar(
    "metadata_operation_budget", default=None
)


@contextmanager
def metadata_operation_budget(
    remaining: Callable[[], float], expired: Callable[[], SnapshotError]
) -> Iterator[None]:
    """Apply a caller deadline to metadata work submitted within this scope."""
    parent = _metadata_budget.get()

    def remaining_with_parent() -> float:
        return min(parent.check(), remaining()) if parent is not None else remaining()

    token = _metadata_budget.set(_MetadataBudget(remaining_with_parent, expired))
    try:
        yield
    finally:
        _metadata_budget.reset(token)


def _check_metadata_budget() -> None:
    if (budget := _metadata_budget.get()) is not None:
        budget.check()


def _async_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url
    if database_url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + database_url.removeprefix("postgresql://")
    raise ValueError("FUNDAMENTAL_SERVICE_DATABASE_URL must use PostgreSQL")


class _AsyncRunner:
    def __init__(self, database_url: str) -> None:
        self._loop = asyncio.new_event_loop()
        self._ready = Event()
        self._thread = Thread(target=self._serve, name="fundamental-db", daemon=True)
        self._scoped_tasks: set[asyncio.Task[object]] = set()
        self._cleanup_tasks: set[asyncio.Task[None]] = set()
        self._engine: AsyncEngine = create_async_engine(
            _async_database_url(database_url),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
        )
        self._thread.start()
        self._ready.wait(timeout=5)

    def _serve(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    def run(
        self,
        coroutine: Coroutine[object, object, _T],
        *,
        publication_timeout: float | None = None,
        cleanup: bool = False,
    ) -> _T:
        if not self._thread.is_alive():
            coroutine.close()
            raise RuntimeError("database event loop is unavailable")
        budget = _metadata_budget.get()
        if cleanup or budget is None:
            token = _metadata_budget.set(None)
            try:
                future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
            finally:
                _metadata_budget.reset(token)
            if publication_timeout is None:
                return future.result(timeout=15)
            if wait((future,), timeout=publication_timeout).done:
                return future.result()
            future.cancel()
            raise ArtifactPublicationDeadlineExceeded()
        return self._run_scoped(coroutine, budget)

    def _run_scoped(
        self, coroutine: Coroutine[object, object, _T], budget: _MetadataBudget
    ) -> _T:
        try:
            budget.check()
        except BaseException:
            coroutine.close()
            raise
        cancelled = Event()
        timer: asyncio.Timeout | None = None

        async def bounded() -> _T:
            nonlocal timer
            try:
                if cancelled.is_set():
                    raise budget.expired()
                timeout = asyncio.timeout(budget.check())
            except BaseException:
                coroutine.close()
                raise
            timer = timeout
            task = asyncio.current_task()
            assert task is not None
            self._scoped_tasks.add(task)
            try:
                async with timeout:
                    result = await coroutine
                    budget.check()
            except TimeoutError:
                if timeout.expired():
                    raise budget.expired() from None
                raise
            finally:
                timer = None
                self._scoped_tasks.discard(task)
            return result

        def expire_async_wait() -> None:
            # Both waiters use one timer so cancellation cannot interrupt cleanup.
            if timer is not None and not timer.expired():
                timer.reschedule(self._loop.time())

        future: Future[_T] = asyncio.run_coroutine_threadsafe(bounded(), self._loop)
        try:
            if wait((future,), timeout=budget.check()).done:
                return future.result()
            raise budget.expired()
        finally:
            if not future.done():
                cancelled.set()
                self._loop.call_soon_threadsafe(expire_async_wait)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection]:
        budget = _metadata_budget.get()

        def check_commit_deadline(_connection: Connection) -> None:
            if budget is not None:
                budget.check()

        async with self._engine.begin() as connection:
            if budget is not None:
                event.listen(
                    connection.sync_connection, "commit", check_commit_deadline
                )
            yield connection
            if budget is not None:
                budget.check()

    def defer_cleanup(self, coroutine: Coroutine[object, object, None]) -> None:
        def start_cleanup() -> None:
            task = self._loop.create_task(coroutine)
            self._cleanup_tasks.add(task)
            task.add_done_callback(self._cleanup_tasks.discard)

        self._loop.call_soon_threadsafe(start_cleanup, context=Context())

    async def _dispose(self) -> None:
        if self._scoped_tasks:
            await asyncio.gather(*self._scoped_tasks, return_exceptions=True)
        if self._cleanup_tasks:
            await asyncio.gather(*self._cleanup_tasks, return_exceptions=True)
        await self._engine.dispose()

    def close(self) -> None:
        if self._thread.is_alive():
            try:
                self.run(self._dispose(), cleanup=True)
            finally:
                self._loop.call_soon_threadsafe(self._loop.stop)
                self._thread.join(timeout=5)


@dataclass(frozen=True)
class MetadataHealth:
    ready: bool
    schema_version: str | None


@dataclass(frozen=True)
class IngestionLockLease:
    lease_id: str
    advisory_key: int


class PostgresMetadataStore:
    """Append-only metadata registry owned by the Fundamental service."""

    def __init__(
        self,
        database_url: str,
        *,
        auto_migrate: bool = False,
        schema: str = SCHEMA,
        data_release_trust_roots: DataReleaseTrustRootsV1 | None = None,
    ) -> None:
        if schema != SCHEMA:
            raise ValueError("Fundamental metadata must use the fundamental schema")
        self.schema = schema
        self.auto_migrate = auto_migrate
        self._data_release_trust_roots = data_release_trust_roots
        self._runner = _AsyncRunner(database_url)
        self._ready = False
        self._health = MetadataHealth(False, None)
        self._schema_capabilities: frozenset[str] = frozenset()
        self._ingestion_lock_connections: dict[str, tuple[int, AsyncConnection]] = {}
        self._close_lock = Lock()
        self._closed = False

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def parser_action_reuse_configured(self) -> bool:
        return self.ready and "sec-parser-actions-v1" in self._schema_capabilities

    @property
    def health(self) -> MetadataHealth:
        return self._health

    @property
    def data_release_trust_roots_configured(self) -> bool:
        return self._data_release_trust_roots is not None

    def start(self) -> None:
        self._start(self._startup)

    def start_read_only(self) -> None:
        self._start(self._inspect_schema)

    def _start(self, operation: Callable[[], Coroutine[object, object, None]]) -> None:
        try:
            self._runner.run(operation())
        except Exception as exc:  # pragma: no cover - exercised by container startup
            self._ready = False
            self._health = MetadataHealth(False, None)
            raise SnapshotError(
                "METADATA_SCHEMA_UNAVAILABLE",
                "Fundamental metadata schema is unavailable",
                retryable=True,
            ) from exc

    async def _startup(self) -> None:
        if self.auto_migrate:
            await self._apply_migration()
        await self._inspect_schema()

    async def _inspect_schema(self) -> None:
        version = await self._schema_version()
        if version != SCHEMA_VERSION:
            raise RuntimeError("Fundamental metadata schema version is incompatible")
        self._schema_capabilities = await self._schema_capability_ids()
        self._ready = True
        self._health = MetadataHealth(True, version)

    async def _schema_capability_ids(self) -> frozenset[str]:
        async with self._runner._engine.connect() as connection:
            table_exists = await connection.scalar(
                text(
                    "SELECT to_regclass('fundamental.schema_capabilities') IS NOT NULL"
                )
            )
            if not table_exists:
                return frozenset()
            result = await connection.execute(
                text("SELECT capability_id FROM fundamental.schema_capabilities")
            )
            return frozenset(str(row[0]) for row in result.all())

    async def _apply_migration(self) -> None:
        migration_dir = resources.files("fundamental_service").joinpath("migrations")
        migrations = sorted(
            (item for item in migration_dir.iterdir() if item.name.endswith(".sql")),
            key=lambda item: item.name,
        )
        for migration in migrations:
            sql = migration.read_text(encoding="utf-8")
            async with self._runner._engine.begin() as connection:
                await connection.execute(text("SELECT 1"))
                raw = await connection.get_raw_connection()
                driver = raw.driver_connection
                if not isinstance(driver, asyncpg.Connection):
                    raise RuntimeError("metadata migrations require PostgreSQL")
                await driver.execute(sql)

    def run_fiscal_admission_history(
        self, operation: Callable[[AsyncConnection], Awaitable[_T]]
    ) -> _T:
        self._require_ready()
        if "fiscal-admission-history-v1" not in self._schema_capabilities:
            raise SnapshotError(
                "FISCAL_ADMISSION_HISTORY_UNAVAILABLE",
                "fiscal admission history capability is unavailable",
            )
        return self._runner.run(self._fiscal_history_transaction(operation))

    async def _fiscal_history_transaction(
        self, operation: Callable[[AsyncConnection], Awaitable[_T]]
    ) -> _T:
        async with self._runner.transaction() as connection:
            return await operation(connection)

    async def _schema_version(self) -> str | None:
        async with self._runner._engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT version FROM fundamental.schema_migrations "
                    "ORDER BY applied_at DESC, version DESC LIMIT 1"
                )
            )
            row = result.first()
            return None if row is None else str(row[0])

    def _require_ready(self) -> None:
        if not self.ready:
            raise SnapshotError(
                "METADATA_NOT_READY",
                "Fundamental metadata store is not ready",
                retryable=True,
            )

    def _require_data_release_capability(self) -> None:
        self._require_ready()
        if DATA_RELEASE_CAPABILITY not in self._schema_capabilities:
            raise DataReleaseError(
                "DATA_RELEASE_SCHEMA_UNAVAILABLE",
                "data release schema capability is unavailable",
                retryable=True,
            )

    @staticmethod
    def _payload_json(payload: object) -> str:
        return canonical_bytes(payload).decode("utf-8")

    @staticmethod
    def _payload_equal(stored: object, payload: object) -> bool:
        return canonical_bytes(stored) == canonical_bytes(payload)

    async def _immutable_put(
        self,
        *,
        table: str,
        key_column: str,
        key: str,
        digest_column: str,
        digest: str,
        payload: object,
    ) -> None:
        async with self._runner._engine.begin() as connection:
            query = text(
                f"SELECT {digest_column}, payload FROM {SCHEMA}.{table} "
                f"WHERE {key_column} = :key"
            )
            existing = (
                (await connection.execute(query, {"key": key})).mappings().first()
            )
            if existing is not None:
                if existing[digest_column] != digest or not self._payload_equal(
                    existing["payload"], payload
                ):
                    raise SnapshotError(
                        "METADATA_IMMUTABLE",
                        f"{table} records are immutable",
                    )
                return
            await connection.execute(
                text(
                    f"INSERT INTO {SCHEMA}.{table}"
                    f"({key_column}, {digest_column}, payload) "
                    "VALUES (:key, :digest, CAST(:payload AS jsonb)) "
                    f"ON CONFLICT ({key_column}) DO NOTHING"
                ),
                {
                    "key": key,
                    "digest": digest,
                    "payload": self._payload_json(payload),
                },
            )
            existing = (
                (await connection.execute(query, {"key": key})).mappings().first()
            )
            if existing is None or existing[digest_column] != digest:
                raise SnapshotError("METADATA_IMMUTABLE", f"{table} publication raced")

    def publish_snapshot(self, snapshot: SourceSnapshotV1) -> None:
        self._require_ready()
        self._runner.run(
            self._immutable_put(
                table="snapshot_manifests",
                key_column="snapshot_id",
                key=snapshot.snapshot_id,
                digest_column="manifest_digest",
                digest=snapshot.manifest_digest,
                payload=snapshot.model_dump(mode="json"),
            )
        )

    def get_snapshot(self, snapshot_id: str) -> SourceSnapshotV1:
        payload = self._get_payload("snapshot_manifests", "snapshot_id", snapshot_id)
        try:
            return SourceSnapshotV1.model_validate_json(canonical_bytes(payload))
        except ValueError as exc:
            raise SnapshotError(
                "METADATA_CORRUPT", "snapshot metadata is invalid"
            ) from exc

    def list_snapshots(self) -> tuple[SourceSnapshotV1, ...]:
        rows = self._list_payloads("snapshot_manifests")
        return tuple(
            SourceSnapshotV1.model_validate_json(canonical_bytes(item)) for item in rows
        )

    def try_acquire_ingestion_lock(
        self, acquisition_key: str
    ) -> IngestionLockLease | None:
        self._require_ready()
        if len(acquisition_key) != 64 or any(
            char not in "0123456789abcdef" for char in acquisition_key
        ):
            raise SnapshotError(
                "INGESTION_KEY_INVALID", "acquisition key must be SHA-256"
            )
        advisory_key = int.from_bytes(
            bytes.fromhex(acquisition_key[:16]), "big", signed=True
        )
        lease = IngestionLockLease(uuid4().hex, advisory_key)
        try:
            return self._runner.run(self._try_acquire_ingestion_lock(lease))
        except BaseException:
            if _metadata_budget.get() is not None:
                self._runner.defer_cleanup(self._release_ingestion_lock(lease.lease_id))
            raise

    def reserve_sec_provider_request_slot(self, min_interval_seconds: float) -> float:
        self._require_ready()
        if not 0 <= min_interval_seconds <= 5:
            raise ValueError("SEC request interval is outside the supported bound")
        return float(
            self._runner.run(
                self._reserve_sec_provider_request_slot(min_interval_seconds)
            )
        )

    async def _reserve_sec_provider_request_slot(
        self, min_interval_seconds: float
    ) -> float:
        async with self._runner.transaction() as connection:
            await connection.execute(
                text(
                    "INSERT INTO fundamental.sec_provider_rate_limits "
                    "(rate_key, next_request_at) "
                    "VALUES ('sec-edgar', clock_timestamp()) "
                    "ON CONFLICT (rate_key) DO NOTHING"
                )
            )
            row = (
                (
                    await connection.execute(
                        text(
                            "SELECT GREATEST(0, EXTRACT(EPOCH FROM "
                            "(next_request_at - clock_timestamp()))) AS wait_seconds "
                            "FROM fundamental.sec_provider_rate_limits "
                            "WHERE rate_key='sec-edgar' FOR UPDATE"
                        )
                    )
                )
                .mappings()
                .one()
            )
            await connection.execute(
                text(
                    "UPDATE fundamental.sec_provider_rate_limits "
                    "SET next_request_at=GREATEST(next_request_at, clock_timestamp()) "
                    "+ (:interval_seconds * INTERVAL '1 second') "
                    "WHERE rate_key='sec-edgar'"
                ),
                {"interval_seconds": min_interval_seconds},
            )
        return float(row["wait_seconds"])

    async def _try_acquire_ingestion_lock(
        self, lease: IngestionLockLease
    ) -> IngestionLockLease | None:
        connection = await self._runner._engine.connect()
        try:
            result = await connection.execute(
                text("SELECT pg_try_advisory_lock(:advisory_key)"),
                {"advisory_key": lease.advisory_key},
            )
            acquired = bool(result.scalar_one())
            _check_metadata_budget()
            await connection.commit()
            if not acquired:
                await connection.close()
                return None
            _check_metadata_budget()
            self._ingestion_lock_connections[lease.lease_id] = (
                lease.advisory_key,
                connection,
            )
            return lease
        except BaseException:
            await self._discard_lock_connection(connection)
            raise

    def release_ingestion_lock(self, lease: IngestionLockLease) -> None:
        self._runner.run(self._release_ingestion_lock(lease.lease_id), cleanup=True)

    def require_ingestion_lock(self, lease: IngestionLockLease) -> datetime:
        self._require_ready()
        return self._runner.run(self._require_ingestion_lock(lease))

    async def _require_ingestion_lock(self, lease: IngestionLockLease) -> datetime:
        held = self._ingestion_lock_connections.get(lease.lease_id)
        if held is None or held[0] != lease.advisory_key or held[1].closed:
            raise SnapshotError(
                "INGESTION_LOCK_LOST", "ingestion lease is no longer held"
            )
        connection = held[1]
        row = (
            (
                await connection.execute(
                    text(
                        "SELECT clock_timestamp() AS observed_at, EXISTS ("
                        "SELECT 1 FROM pg_catalog.pg_locks WHERE locktype='advisory' "
                        "AND pid=pg_backend_pid() AND granted AND objsubid=1 "
                        "AND classid=:high AND objid=:low) AS held"
                    ),
                    {
                        "high": (lease.advisory_key & ((1 << 64) - 1)) >> 32,
                        "low": lease.advisory_key & ((1 << 32) - 1),
                    },
                )
            )
            .mappings()
            .one()
        )
        _check_metadata_budget()
        await connection.commit()
        if not row["held"]:
            raise SnapshotError(
                "INGESTION_LOCK_LOST", "ingestion lease is no longer held"
            )
        observed_at = row["observed_at"]
        if not isinstance(observed_at, datetime) or observed_at.utcoffset() is None:
            raise SnapshotError(
                "INGESTION_LOCK_LOST", "ingestion lease clock is invalid"
            )
        return observed_at

    @staticmethod
    async def _discard_lock_connection(connection: AsyncConnection) -> None:
        try:
            await connection.invalidate()
        finally:
            await connection.close()

    async def _release_ingestion_lock(self, lease_id: str) -> None:
        held = self._ingestion_lock_connections.pop(lease_id, None)
        if held is None:
            return
        advisory_key, connection = held
        try:
            async with asyncio.timeout(5):
                if not connection.closed:
                    await connection.execute(
                        text("SELECT pg_advisory_unlock(:advisory_key)"),
                        {"advisory_key": advisory_key},
                    )
                    await connection.commit()
                await connection.close()
        except BaseException:
            await self._discard_lock_connection(connection)
            raise

    def get_sec_ingestion(
        self,
        acquisition_key: str,
        *,
        expected_acquisition_payload: object | None = None,
    ) -> SecIngestionResponseV1 | None:
        self._require_ready()
        payload = self._runner.run(
            self._get_sec_ingestion(acquisition_key, expected_acquisition_payload)
        )
        if payload is None:
            return None
        return SecIngestionResponseV1.model_validate_json(canonical_bytes(payload))

    async def _get_sec_ingestion(
        self, acquisition_key: str, expected_acquisition_payload: object | None
    ) -> dict[str, Any] | None:
        async with self._runner._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            "SELECT acquisition_payload, result_payload FROM "
                            "fundamental.sec_ingestion_acquisitions "
                            "WHERE acquisition_key=:acquisition_key"
                        ),
                        {"acquisition_key": acquisition_key},
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        if expected_acquisition_payload is not None and not self._payload_equal(
            row["acquisition_payload"], expected_acquisition_payload
        ):
            raise SnapshotError(
                "INGESTION_KEY_COLLISION",
                "canonical acquisition key identifies another request",
            )
        return dict(row["result_payload"])

    def publish_sec_ingestion(
        self,
        *,
        acquisition_key: str,
        acquisition_payload: object,
        snapshot: SourceSnapshotV1,
        facts: tuple[CanonicalFactV1, ...],
        result: SecIngestionResponseV1,
        caller_principal: str,
        organization_id: str,
    ) -> SecIngestionResponseV1:
        self._require_ready()
        if not acquisition_key or len(acquisition_key) != 64:
            raise SnapshotError(
                "INGESTION_KEY_INVALID", "acquisition key must be SHA-256"
            )
        if (
            result.snapshot_id != snapshot.snapshot_id
            or result.manifest_digest != snapshot.manifest_digest
        ):
            raise SnapshotError(
                "INGESTION_RESULT_MISMATCH", "result does not match snapshot manifest"
            )
        source_hashes = {record.content_hash for record in snapshot.source_records}
        if any(fact.source.content_hash not in source_hashes for fact in facts):
            raise SnapshotError(
                "INGESTION_FACT_SOURCE_MISMATCH",
                "canonical facts must reference bytes in the snapshot",
            )
        if tuple(sorted(fact.fact_id for fact in facts)) != result.canonical_fact_ids:
            raise SnapshotError(
                "INGESTION_RESULT_MISMATCH",
                "canonical facts do not match the response fact references",
            )
        return self._runner.run(
            self._publish_sec_ingestion(
                acquisition_key=acquisition_key,
                acquisition_payload=acquisition_payload,
                snapshot=snapshot,
                facts=facts,
                result=result,
                caller_principal=caller_principal,
                organization_id=organization_id,
            )
        )

    async def _publish_sec_ingestion(
        self,
        *,
        acquisition_key: str,
        acquisition_payload: object,
        snapshot: SourceSnapshotV1,
        facts: tuple[CanonicalFactV1, ...],
        result: SecIngestionResponseV1,
        caller_principal: str,
        organization_id: str,
    ) -> SecIngestionResponseV1:
        async with self._runner._engine.begin() as connection:
            existing_acquisition = (
                (
                    await connection.execute(
                        text(
                            "SELECT acquisition_payload, result_payload "
                            "FROM fundamental.sec_ingestion_acquisitions "
                            "WHERE acquisition_key=:acquisition_key"
                        ),
                        {"acquisition_key": acquisition_key},
                    )
                )
                .mappings()
                .first()
            )
            if existing_acquisition is not None:
                if not self._payload_equal(
                    existing_acquisition["acquisition_payload"], acquisition_payload
                ):
                    raise SnapshotError(
                        "INGESTION_KEY_COLLISION",
                        "canonical acquisition key identifies another request",
                    )
                return SecIngestionResponseV1.model_validate_json(
                    canonical_bytes(existing_acquisition["result_payload"])
                )

            await connection.execute(
                text(
                    "INSERT INTO fundamental.snapshot_manifests "
                    "(snapshot_id, manifest_digest, payload) "
                    "VALUES (:snapshot_id, :digest, CAST(:payload AS jsonb)) "
                    "ON CONFLICT (snapshot_id) DO NOTHING"
                ),
                {
                    "snapshot_id": snapshot.snapshot_id,
                    "digest": snapshot.manifest_digest,
                    "payload": self._payload_json(snapshot.model_dump(mode="json")),
                },
            )
            stored_snapshot = (
                (
                    await connection.execute(
                        text(
                            "SELECT manifest_digest, payload FROM "
                            "fundamental.snapshot_manifests "
                            "WHERE snapshot_id=:snapshot_id"
                        ),
                        {"snapshot_id": snapshot.snapshot_id},
                    )
                )
                .mappings()
                .first()
            )
            if (
                stored_snapshot is None
                or stored_snapshot["manifest_digest"] != snapshot.manifest_digest
                or not self._payload_equal(
                    stored_snapshot["payload"], snapshot.model_dump(mode="json")
                )
            ):
                raise SnapshotError(
                    "METADATA_IMMUTABLE", "snapshot manifest is already different"
                )

            for fact in facts:
                await self._publish_fact_in_transaction(connection, fact)
                await connection.execute(
                    text(
                        "INSERT INTO fundamental.snapshot_facts (snapshot_id, fact_id) "
                        "VALUES (:snapshot_id, :fact_id) ON CONFLICT DO NOTHING"
                    ),
                    {"snapshot_id": snapshot.snapshot_id, "fact_id": fact.fact_id},
                )

            await connection.execute(
                text(
                    "INSERT INTO fundamental.sec_ingestion_acquisitions "
                    "(acquisition_key, acquisition_payload, snapshot_id, fact_ids, "
                    "result_payload, caller_principal, organization_id, "
                    "correlation_id) "
                    "VALUES (:acquisition_key, CAST(:acquisition_payload AS jsonb), "
                    ":snapshot_id, CAST(:fact_ids AS jsonb), "
                    "CAST(:result_payload AS jsonb), :caller_principal, "
                    ":organization_id, :correlation_id)"
                ),
                {
                    "acquisition_key": acquisition_key,
                    "acquisition_payload": self._payload_json(acquisition_payload),
                    "snapshot_id": snapshot.snapshot_id,
                    "fact_ids": self._payload_json(result.canonical_fact_ids),
                    "result_payload": self._payload_json(
                        result.model_dump(mode="json")
                    ),
                    "caller_principal": caller_principal,
                    "organization_id": organization_id,
                    "correlation_id": result.correlation_id,
                },
            )
        return result

    def publish_fact(self, fact: CanonicalFactV1) -> None:
        self._require_ready()
        self._runner.run(self._publish_fact(fact))

    async def _publish_fact(self, fact: CanonicalFactV1) -> None:
        async with self._runner._engine.begin() as connection:
            await self._publish_fact_in_transaction(connection, fact)

    async def _publish_fact_in_transaction(
        self, connection: AsyncConnection, fact: CanonicalFactV1
    ) -> None:
        """Keep the first complete view; source identity excludes PIT annotations."""
        digest = canonical_fact_digest(fact)
        await connection.execute(
            text(
                "INSERT INTO fundamental.canonical_facts "
                "(fact_id, fact_digest, payload) "
                "VALUES (:fact_id, :digest, CAST(:payload AS jsonb)) "
                "ON CONFLICT (fact_id) DO NOTHING"
            ),
            {
                "fact_id": fact.fact_id,
                "digest": digest,
                "payload": self._payload_json(fact.model_dump(mode="json")),
            },
        )
        stored = (
            (
                await connection.execute(
                    text(
                        "SELECT fact_digest, payload FROM fundamental.canonical_facts WHERE fact_id=:fact_id"
                    ),
                    {"fact_id": fact.fact_id},
                )
            )
            .mappings()
            .first()
        )
        if stored is None or stored["fact_digest"] != digest:
            raise SnapshotError(
                "METADATA_IMMUTABLE", "canonical fact is already different"
            )
        try:
            retained = CanonicalFactV1.model_validate_json(
                canonical_bytes(stored["payload"])
            )
        except ValueError as error:
            raise SnapshotError(
                "METADATA_CORRUPT", "canonical fact metadata is invalid"
            ) from error
        if canonical_fact_digest(retained) != digest:
            raise SnapshotError(
                "METADATA_IMMUTABLE", "canonical fact is already different"
            )

    def get_fact(self, fact_id: str) -> CanonicalFactV1:
        try:
            payload = self._get_payload("canonical_facts", "fact_id", fact_id)
        except SnapshotError as exc:
            if exc.code == "SNAPSHOT_NOT_FOUND":
                raise SnapshotError(
                    "FACT_NOT_FOUND", f"fact {fact_id} is unavailable"
                ) from exc
            raise
        try:
            return CanonicalFactV1.model_validate_json(canonical_bytes(payload))
        except ValueError as exc:
            raise SnapshotError(
                "METADATA_CORRUPT", "canonical fact metadata is invalid"
            ) from exc

    def list_facts(self) -> tuple[CanonicalFactV1, ...]:
        return tuple(
            CanonicalFactV1.model_validate_json(canonical_bytes(item))
            for item in self._list_payloads("canonical_facts")
        )

    def publish_mapping(self, mapping: CanonicalMappingV1) -> None:
        self._require_ready()
        payload = mapping.model_dump(mode="json")
        self._runner.run(
            self._immutable_put(
                table="mapping_decisions",
                key_column="mapping_id",
                key=mapping.decision_id,
                digest_column="mapping_digest",
                digest=sha256_digest(payload),
                payload=payload,
            )
        )

    def get_mapping(self, mapping_id: str) -> CanonicalMappingV1:
        try:
            payload = self._get_payload("mapping_decisions", "mapping_id", mapping_id)
        except SnapshotError as exc:
            if exc.code == "SNAPSHOT_NOT_FOUND":
                raise SnapshotError(
                    "MAPPING_NOT_FOUND", f"mapping {mapping_id} is unavailable"
                ) from exc
            raise
        try:
            return CanonicalMappingV1.model_validate_json(canonical_bytes(payload))
        except ValueError as exc:
            raise SnapshotError(
                "METADATA_CORRUPT", "mapping metadata is invalid"
            ) from exc

    def list_mappings(self) -> tuple[CanonicalMappingV1, ...]:
        return tuple(
            CanonicalMappingV1.model_validate_json(canonical_bytes(item))
            for item in self._list_payloads("mapping_decisions")
        )

    def publish_data_release_candidate(
        self,
        manifest: PublicationManifest,
        verification: PublicationVerification,
        *,
        fiscal_observation: FiscalActivationObservationV1 | None = None,
    ) -> None:
        self._require_data_release_capability()
        manifest = decode_release_manifest(canonical_bytes(manifest))
        verification = decode_release_verification(canonical_bytes(verification))
        if self._data_release_trust_roots is None:
            raise DataReleaseError(
                "DATA_RELEASE_TRUST_ROOTS_UNCONFIGURED",
                "data release trust roots are required to publish a candidate",
            )
        verify_publication_pair(manifest, verification, self._data_release_trust_roots)
        if isinstance(manifest, FiscalReleaseManifestV1) != (
            fiscal_observation is not None
        ):
            raise DataReleaseError(
                "FISCAL_PUBLICATION_OBSERVATION_REQUIRED",
                "fiscal publication requires its complete owning observation",
            )
        self._runner.run(
            self._publish_data_release_candidate(
                manifest, verification, fiscal_observation=fiscal_observation
            )
        )

    async def _publish_data_release_candidate(
        self,
        manifest: PublicationManifest,
        verification: PublicationVerification,
        *,
        fiscal_observation: FiscalActivationObservationV1 | None = None,
    ) -> None:
        from .fiscal_admission_history import PostgresFiscalAdmissionHistory

        async with self._runner._engine.begin() as connection:
            if fiscal_observation is not None:
                await PostgresFiscalAdmissionHistory(self).validate_activation(
                    fiscal_observation, connection
                )
            await connection.execute(
                text(
                    "INSERT INTO fundamental.data_release_manifests "
                    "(manifest_digest, profile_id, release_id, payload) VALUES "
                    "(:digest, :profile_id, :release_id, CAST(:payload AS jsonb)) "
                    "ON CONFLICT (manifest_digest) DO NOTHING"
                ),
                {
                    "digest": manifest.manifest_digest,
                    "profile_id": manifest.profile_id,
                    "release_id": manifest.release_id,
                    "payload": self._payload_json(manifest.model_dump(mode="json")),
                },
            )
            stored_manifest = (
                (
                    await connection.execute(
                        text(
                            "SELECT profile_id, release_id, payload "
                            "FROM fundamental.data_release_manifests "
                            "WHERE manifest_digest=:digest"
                        ),
                        {"digest": manifest.manifest_digest},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if (
                stored_manifest is None
                or stored_manifest["profile_id"] != manifest.profile_id
                or stored_manifest["release_id"] != manifest.release_id
                or not self._payload_equal(
                    stored_manifest["payload"], manifest.model_dump(mode="json")
                )
            ):
                raise DataReleaseError(
                    "DATA_RELEASE_IMMUTABLE",
                    "a stored data release manifest cannot be replaced",
                )

            await connection.execute(
                text(
                    "INSERT INTO fundamental.data_release_verifications "
                    "(manifest_digest, verification_digest, payload) VALUES "
                    "(:manifest_digest, :verification_digest, CAST(:payload AS jsonb)) "
                    "ON CONFLICT (manifest_digest) DO NOTHING"
                ),
                {
                    "manifest_digest": manifest.manifest_digest,
                    "verification_digest": verification.verification_digest,
                    "payload": self._payload_json(verification.model_dump(mode="json")),
                },
            )
            stored_verification = (
                (
                    await connection.execute(
                        text(
                            "SELECT verification_digest, payload "
                            "FROM fundamental.data_release_verifications "
                            "WHERE manifest_digest=:manifest_digest"
                        ),
                        {"manifest_digest": manifest.manifest_digest},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if (
                stored_verification is None
                or stored_verification["verification_digest"]
                != verification.verification_digest
                or not self._payload_equal(
                    stored_verification["payload"],
                    verification.model_dump(mode="json"),
                )
            ):
                raise DataReleaseError(
                    "DATA_RELEASE_IMMUTABLE",
                    "stored data release verification cannot be replaced",
                )

            if fiscal_observation is not None:
                await PostgresFiscalAdmissionHistory.require_activation_clock(
                    fiscal_observation, connection
                )

    def get_active_data_release(self, profile_id: str) -> ActiveDataReleaseV1 | None:
        self._require_data_release_capability()
        return self._runner.run(self._get_active_data_release(profile_id))

    def get_data_release_manifest(
        self, manifest_digest: str
    ) -> PublicationManifest | None:
        self._require_data_release_capability()
        return self._runner.run(self._get_data_release_manifest(manifest_digest))

    def get_data_release_verification(
        self, manifest_digest: str
    ) -> PublicationVerification | None:
        self._require_data_release_capability()
        return self._runner.run(self._get_data_release_verification(manifest_digest))

    async def _get_data_release_verification(
        self, manifest_digest: str
    ) -> PublicationVerification | None:
        async with self._runner._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            "SELECT verification.payload, verification.verification_digest, "
                            "manifest.payload AS manifest_payload "
                            "FROM fundamental.data_release_verifications AS verification "
                            "JOIN fundamental.data_release_manifests AS manifest "
                            "USING (manifest_digest) "
                            "WHERE verification.manifest_digest=:manifest_digest"
                        ),
                        {"manifest_digest": manifest_digest},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        verification = decode_release_verification(canonical_bytes(row["payload"]))
        manifest = decode_release_manifest(canonical_bytes(row["manifest_payload"]))
        if (
            verification.verification_digest != row["verification_digest"]
            or verification.manifest_digest != manifest_digest
            or manifest.manifest_digest != manifest_digest
        ):
            raise DataReleaseError(
                "DATA_RELEASE_VERIFICATION_MISMATCH",
                "stored release verification differs from its persisted identity",
            )
        if self._data_release_trust_roots is None:
            raise DataReleaseError(
                "DATA_RELEASE_TRUST_ROOTS_UNCONFIGURED",
                "data release trust roots are required to read verification evidence",
            )
        verify_publication_pair(manifest, verification, self._data_release_trust_roots)
        return verification

    async def _get_data_release_manifest(
        self, manifest_digest: str
    ) -> PublicationManifest | None:
        async with self._runner._engine.connect() as connection:
            payload = await connection.scalar(
                text(
                    "SELECT manifest.payload "
                    "FROM fundamental.data_release_manifests AS manifest "
                    "JOIN fundamental.data_release_verifications AS verification "
                    "USING (manifest_digest) "
                    "WHERE manifest.manifest_digest=:manifest_digest"
                ),
                {"manifest_digest": manifest_digest},
            )
        if payload is None:
            return None
        manifest = decode_release_manifest(canonical_bytes(payload))
        if manifest.manifest_digest != manifest_digest:
            raise DataReleaseError(
                "DATA_RELEASE_VERIFICATION_MISMATCH", "stored manifest identity differs"
            )
        await self._get_data_release_verification(manifest_digest)
        return manifest

    async def _get_active_data_release(
        self, profile_id: str
    ) -> ActiveDataReleaseV1 | None:
        async with self._runner._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            "SELECT manifest_digest, revision, activated_at "
                            "FROM fundamental.active_data_release_pointers "
                            "WHERE profile_id=:profile_id"
                        ),
                        {"profile_id": profile_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None or int(row["revision"]) == 0:
            return None
        return ActiveDataReleaseV1(
            profile_id=profile_id,
            manifest_digest=str(row["manifest_digest"]),
            revision=int(row["revision"]),
            activated_at=row["activated_at"],
        )

    def get_active_data_release_with_manifest(
        self, profile_id: str
    ) -> ActivePublication | None:
        self._require_data_release_capability()
        return self._runner.run(self._get_active_data_release_with_manifest(profile_id))

    async def _get_active_data_release_with_manifest(
        self, profile_id: str
    ) -> ActivePublication | None:
        async with self._runner._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            "SELECT pointer.profile_id, pointer.manifest_digest, "
                            "pointer.revision, pointer.activated_at, manifest.payload "
                            "FROM fundamental.active_data_release_pointers AS pointer "
                            "JOIN fundamental.data_release_manifests AS manifest "
                            "USING (manifest_digest) "
                            "WHERE pointer.profile_id=:profile_id "
                            "AND pointer.revision > 0"
                        ),
                        {"profile_id": profile_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        active = ActiveDataReleaseV1(
            profile_id=str(row["profile_id"]),
            manifest_digest=str(row["manifest_digest"]),
            revision=int(row["revision"]),
            activated_at=row["activated_at"],
        )
        manifest = decode_release_manifest(canonical_bytes(row["payload"]))
        await self._get_data_release_verification(active.manifest_digest)
        return active_publication(active, manifest)

    def compare_and_swap_data_release(
        self,
        command: DataReleaseActivationCommandV1,
        *,
        fiscal_observation: FiscalActivationObservationV1 | None = None,
    ) -> ActiveDataReleaseV1:
        self._require_data_release_capability()
        return self._runner.run(
            self._compare_and_swap_data_release(
                command, fiscal_observation=fiscal_observation
            )
        )

    async def _compare_and_swap_data_release(
        self,
        command: DataReleaseActivationCommandV1,
        *,
        fiscal_observation: FiscalActivationObservationV1 | None = None,
    ) -> ActiveDataReleaseV1:
        from .fiscal_admission_history import PostgresFiscalAdmissionHistory

        async with self._runner._engine.begin() as connection:
            await connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:command_id, 0))"),
                {"command_id": command.command_id},
            )
            previous_command = await self._release_activation_audit(
                connection, command.command_id
            )
            if previous_command is not None:
                return self._replay_activation_command(previous_command, command)

            if fiscal_observation is not None:
                await PostgresFiscalAdmissionHistory(self).validate_activation(
                    fiscal_observation, connection
                )

            candidate = (
                (
                    await connection.execute(
                        text(
                            "SELECT manifest.profile_id, manifest.payload "
                            "FROM fundamental.data_release_manifests AS manifest "
                            "JOIN fundamental.data_release_verifications AS verification "
                            "USING (manifest_digest) "
                            "WHERE manifest.manifest_digest=:manifest_digest"
                        ),
                        {"manifest_digest": command.manifest_digest},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if candidate is None or candidate["profile_id"] != command.profile_id:
                raise DataReleaseError(
                    "DATA_RELEASE_CANDIDATE_UNVERIFIED",
                    "verified data release candidate was not found for this profile",
                )
            candidate_manifest = decode_release_manifest(
                canonical_bytes(candidate["payload"])
            )
            if isinstance(candidate_manifest, FiscalReleaseManifestV1) != (
                fiscal_observation is not None
            ):
                raise DataReleaseError(
                    "FISCAL_ACTIVATION_OBSERVATION_REQUIRED",
                    "fiscal activation requires a complete owning current observation",
                )
            if command.operation == "rollback":
                previously_active = await connection.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 "
                        "FROM fundamental.data_release_activation_audit "
                        "WHERE profile_id=:profile_id "
                        "AND to_manifest_digest=:manifest_digest)"
                    ),
                    {
                        "profile_id": command.profile_id,
                        "manifest_digest": command.manifest_digest,
                    },
                )
                if not previously_active:
                    raise DataReleaseError(
                        "DATA_RELEASE_ROLLBACK_TARGET_INVALID",
                        "rollback target was never active for this profile",
                    )

            await connection.execute(
                text(
                    "INSERT INTO fundamental.active_data_release_pointers "
                    "(profile_id, manifest_digest, revision, activated_at) "
                    "VALUES (:profile_id, NULL, 0, NULL) "
                    "ON CONFLICT (profile_id) DO NOTHING"
                ),
                {"profile_id": command.profile_id},
            )
            pointer = (
                (
                    await connection.execute(
                        text(
                            "SELECT manifest_digest, revision "
                            "FROM fundamental.active_data_release_pointers "
                            "WHERE profile_id=:profile_id FOR UPDATE"
                        ),
                        {"profile_id": command.profile_id},
                    )
                )
                .mappings()
                .one()
            )
            current_digest = pointer["manifest_digest"]
            current_revision = int(pointer["revision"])
            if (
                current_revision != command.expected_revision
                or current_digest != command.expected_manifest_digest
            ):
                raise DataReleaseError(
                    "DATA_RELEASE_POINTER_CONFLICT",
                    "active data release changed; reread and revalidate the candidate",
                    retryable=True,
                )

            if fiscal_observation is not None:
                await PostgresFiscalAdmissionHistory.require_activation_clock(
                    fiscal_observation, connection
                )

            activated = (
                (
                    await connection.execute(
                        text(
                            "UPDATE fundamental.active_data_release_pointers "
                            "SET manifest_digest=:manifest_digest, "
                            "revision=revision + 1, activated_at=clock_timestamp() "
                            "WHERE profile_id=:profile_id "
                            "RETURNING revision, activated_at"
                        ),
                        {
                            "profile_id": command.profile_id,
                            "manifest_digest": command.manifest_digest,
                        },
                    )
                )
                .mappings()
                .one()
            )
            await connection.execute(
                text(
                    "INSERT INTO fundamental.data_release_activation_audit "
                    "(command_id, profile_id, operation, expected_revision, "
                    "expected_manifest_digest, from_manifest_digest, "
                    "to_manifest_digest, actor_id, organization_id, correlation_id, "
                    "reason, resulting_revision, activated_at) VALUES "
                    "(:command_id, :profile_id, :operation, :expected_revision, "
                    ":expected_manifest_digest, :from_manifest_digest, "
                    ":to_manifest_digest, :actor_id, :organization_id, "
                    ":correlation_id, :reason, :resulting_revision, :activated_at)"
                ),
                {
                    "command_id": command.command_id,
                    "profile_id": command.profile_id,
                    "operation": command.operation,
                    "expected_revision": command.expected_revision,
                    "expected_manifest_digest": command.expected_manifest_digest,
                    "from_manifest_digest": current_digest,
                    "to_manifest_digest": command.manifest_digest,
                    "actor_id": command.actor_id,
                    "organization_id": command.organization_id,
                    "correlation_id": command.correlation_id,
                    "reason": command.reason,
                    "resulting_revision": int(activated["revision"]),
                    "activated_at": activated["activated_at"],
                },
            )
        return ActiveDataReleaseV1(
            profile_id=command.profile_id,
            manifest_digest=command.manifest_digest,
            revision=int(activated["revision"]),
            activated_at=activated["activated_at"],
        )

    async def _release_activation_audit(
        self, connection: AsyncConnection, command_id: str
    ) -> dict[str, Any] | None:
        result = await connection.execute(
            text(
                "SELECT command_id, profile_id, operation, expected_revision, "
                "expected_manifest_digest, from_manifest_digest, to_manifest_digest, "
                "actor_id, organization_id, correlation_id, reason, "
                "resulting_revision, activated_at "
                "FROM fundamental.data_release_activation_audit "
                "WHERE command_id=:command_id"
            ),
            {"command_id": command_id},
        )
        row = result.mappings().one_or_none()
        return None if row is None else dict(row)

    @staticmethod
    def _replay_activation_command(
        row: dict[str, Any], command: DataReleaseActivationCommandV1
    ) -> ActiveDataReleaseV1:
        matches = (
            row["profile_id"] == command.profile_id
            and row["operation"] == command.operation
            and int(row["expected_revision"]) == command.expected_revision
            and row["expected_manifest_digest"] == command.expected_manifest_digest
            and row["from_manifest_digest"] == command.expected_manifest_digest
            and row["to_manifest_digest"] == command.manifest_digest
            and row["actor_id"] == command.actor_id
            and row["organization_id"] == command.organization_id
            and row["correlation_id"] == command.correlation_id
            and row["reason"] == command.reason
        )
        if not matches:
            raise DataReleaseError(
                "DATA_RELEASE_IDEMPOTENCY_CONFLICT",
                "command ID was already used for a different activation",
            )
        return ActiveDataReleaseV1(
            profile_id=command.profile_id,
            manifest_digest=command.manifest_digest,
            revision=int(row["resulting_revision"]),
            activated_at=row["activated_at"],
        )

    def publish_release_manifest(self, manifest: ReleaseManifestV1) -> None:
        self._require_ready()
        self._runner.run(
            self._immutable_put(
                table="release_manifests",
                key_column="manifest_digest",
                key=manifest.manifest_digest,
                digest_column="manifest_digest",
                digest=manifest.manifest_digest,
                payload=manifest.model_dump(mode="json"),
            )
        )

    def publish_model(
        self, model: object, *, model_id: str, model_version: str
    ) -> None:
        self._publish_versioned(
            "model_releases", "model_id", model_id, model_version, model
        )

    def publish_policy(
        self, policy: object, *, policy_id: str, policy_version: str
    ) -> None:
        self._publish_versioned(
            "policy_releases", "policy_id", policy_id, policy_version, policy
        )

    def get_model(self, model_id: str, model_version: str) -> ModelSpecV1:
        payload = self._get_versioned_payload(
            "model_releases", "model_id", model_id, "model_version", model_version
        )
        try:
            return ModelSpecV1.model_validate_json(canonical_bytes(payload))
        except ValueError as exc:
            raise SnapshotError(
                "METADATA_CORRUPT", "model metadata is invalid"
            ) from exc

    def list_models(self) -> tuple[ModelSpecV1, ...]:
        return tuple(
            ModelSpecV1.model_validate_json(canonical_bytes(item))
            for item in self._list_payloads("model_releases")
        )

    def get_policy(self, policy_id: str, policy_version: str) -> PolicyRecordV1:
        payload = self._get_versioned_payload(
            "policy_releases",
            "policy_id",
            policy_id,
            "policy_version",
            policy_version,
        )
        try:
            return PolicyRecordV1.model_validate_json(canonical_bytes(payload))
        except ValueError as exc:
            raise SnapshotError(
                "METADATA_CORRUPT", "policy metadata is invalid"
            ) from exc

    def list_policies(self) -> tuple[PolicyRecordV1, ...]:
        return tuple(
            PolicyRecordV1.model_validate_json(canonical_bytes(item))
            for item in self._list_payloads("policy_releases")
        )

    def _publish_versioned(
        self, table: str, key_column: str, key: str, version: str, payload: object
    ) -> None:
        self._require_ready()
        digest = sha256_digest(payload)
        self._runner.run(
            self._put_versioned(table, key_column, key, version, digest, payload)
        )

    async def _put_versioned(
        self,
        table: str,
        key_column: str,
        key: str,
        version: str,
        digest: str,
        payload: object,
    ) -> None:
        version_column = (
            "policy_version" if table == "policy_releases" else "model_version"
        )
        digest_column = (
            "policy_digest" if table == "policy_releases" else "model_digest"
        )
        async with self._runner._engine.begin() as connection:
            existing = (
                (
                    await connection.execute(
                        text(
                            f"SELECT payload, {digest_column} AS digest "
                            f"FROM {SCHEMA}.{table} WHERE {key_column}=:key "
                            f"AND {version_column}=:version"
                        ),
                        {"key": key, "version": version},
                    )
                )
                .mappings()
                .first()
            )
            if existing is not None:
                if existing["digest"] != digest or not self._payload_equal(
                    existing["payload"], payload
                ):
                    raise SnapshotError(
                        "METADATA_IMMUTABLE", f"{table} records are immutable"
                    )
                return
            await connection.execute(
                text(
                    f"INSERT INTO {SCHEMA}.{table}"
                    f"({key_column}, {version_column}, {digest_column}, payload) "
                    "VALUES (:key, :version, :digest, CAST(:payload AS jsonb)) "
                    f"ON CONFLICT ({key_column}, {version_column}) DO NOTHING"
                ),
                {
                    "key": key,
                    "version": version,
                    "digest": digest,
                    "payload": self._payload_json(payload),
                },
            )
            existing = (
                (
                    await connection.execute(
                        text(
                            f"SELECT payload, {digest_column} AS digest "
                            f"FROM {SCHEMA}.{table} WHERE {key_column}=:key "
                            f"AND {version_column}=:version"
                        ),
                        {"key": key, "version": version},
                    )
                )
                .mappings()
                .first()
            )
            if existing is None or existing["digest"] != digest:
                raise SnapshotError("METADATA_IMMUTABLE", f"{table} publication raced")
            if not self._payload_equal(existing["payload"], payload):
                raise SnapshotError(
                    "METADATA_IMMUTABLE", f"{table} records are immutable"
                )

    def _get_versioned_payload(
        self,
        table: str,
        key_column: str,
        key: str,
        version_column: str,
        version: str,
    ) -> dict[str, Any]:
        self._require_ready()
        payload = self._runner.run(
            self._get_versioned_payload_async(
                table, key_column, key, version_column, version
            )
        )
        if payload is None:
            raise SnapshotError(
                "RELEASE_NOT_FOUND", f"{key} version {version} is unavailable"
            )
        return payload

    async def _get_versioned_payload_async(
        self,
        table: str,
        key_column: str,
        key: str,
        version_column: str,
        version: str,
    ) -> dict[str, Any] | None:
        async with self._runner._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            f"SELECT payload FROM {SCHEMA}.{table} "
                            f"WHERE {key_column}=:key AND {version_column}=:version"
                        ),
                        {"key": key, "version": version},
                    )
                )
                .mappings()
                .first()
            )
        return None if row is None else dict(row["payload"])

    def content_byte_length(self, content_hash: str, *, media_type: str) -> int:
        self._require_ready()
        value = self._runner.run(self._content_byte_length(content_hash, media_type))
        if value is None:
            raise SnapshotError(
                "CONTENT_REGISTRATION_UNAVAILABLE",
                "retained content registration is missing",
            )
        return value

    async def _content_byte_length(
        self, content_hash: str, media_type: str
    ) -> int | None:
        async with self._runner._engine.connect() as connection:
            value = await connection.scalar(
                text(
                    "SELECT byte_length FROM fundamental.content_objects "
                    "WHERE content_hash=:digest AND media_type=:media"
                ),
                {"digest": content_hash, "media": media_type},
            )
            return int(value) if value is not None else None

    def register_content(
        self, content_hash: str, *, media_type: str, byte_length: int
    ) -> None:
        self._require_ready()
        if len(content_hash) != 64 or any(
            char not in "0123456789abcdef" for char in content_hash
        ):
            raise SnapshotError(
                "SOURCE_HASH_INVALID", "content hash must be lowercase SHA-256"
            )
        self._runner.run(self._register_content(content_hash, media_type, byte_length))

    def publish_source_audit(
        self,
        *,
        acquisition_key: str,
        caller_principal: str,
        organization_id: str,
        correlation_id: str,
        source_hashes: tuple[str, ...],
        outcome: str,
    ) -> None:
        self._require_ready()
        self._runner.run(
            self._publish_source_audit(
                acquisition_key=acquisition_key,
                caller_principal=caller_principal,
                organization_id=organization_id,
                correlation_id=correlation_id,
                source_hashes=source_hashes,
                outcome=outcome,
            )
        )

    async def _publish_source_audit(
        self,
        *,
        acquisition_key: str,
        caller_principal: str,
        organization_id: str,
        correlation_id: str,
        source_hashes: tuple[str, ...],
        outcome: str,
    ) -> None:
        async with self._runner._engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO fundamental.source_acquisition_audits "
                    "(acquisition_key, caller_principal, organization_id, "
                    "correlation_id, source_hashes, outcome) VALUES "
                    "(:acquisition_key, :caller_principal, :organization_id, "
                    ":correlation_id, CAST(:source_hashes AS jsonb), :outcome)"
                ),
                {
                    "acquisition_key": acquisition_key,
                    "caller_principal": caller_principal,
                    "organization_id": organization_id,
                    "correlation_id": correlation_id,
                    "source_hashes": self._payload_json(source_hashes),
                    "outcome": outcome,
                },
            )

    def has_content_hash(
        self, content_hash: str, *, media_type: str | None = None
    ) -> bool:
        self._require_ready()
        return bool(self._runner.run(self._has_content_hash(content_hash, media_type)))

    async def _has_content_hash(
        self, content_hash: str, media_type: str | None
    ) -> bool:
        async with self._runner._engine.connect() as connection:
            media_clause = " AND media_type=:media_type" if media_type else ""
            result = await connection.execute(
                text(
                    "SELECT 1 FROM fundamental.content_objects "
                    f"WHERE content_hash=:content_hash{media_clause}"
                ),
                {"content_hash": content_hash, "media_type": media_type},
            )
            return result.first() is not None

    async def _register_content(
        self, content_hash: str, media_type: str, byte_length: int
    ) -> None:
        async with self._runner.transaction() as connection:
            await connection.execute(
                text(
                    "INSERT INTO fundamental.content_objects"
                    "(content_hash, media_type, byte_length, volume) "
                    "VALUES (:hash, :media_type, :byte_length, :volume) "
                    "ON CONFLICT (content_hash, media_type) DO NOTHING"
                ),
                {
                    "hash": content_hash,
                    "media_type": media_type,
                    "byte_length": byte_length,
                    "volume": "fundamental-service-content",
                },
            )

    def publish_artifact(
        self,
        record: ArtifactRecordV1,
        *,
        publication_budget: Callable[[], float] | None = None,
    ) -> bool:
        self._require_ready()
        if _metadata_budget.get() is not None:
            if publication_budget is None:
                return self._runner.run(self._publish_scoped_artifact(record))
            with metadata_operation_budget(
                publication_budget, ArtifactPublicationDeadlineExceeded
            ):
                return self._runner.run(self._publish_scoped_artifact(record))
        remaining = check_publication_budget(publication_budget)
        return bool(
            self._runner.run(
                self._publish_artifact(record, publication_budget),
                publication_timeout=remaining,
            )
        )

    async def _publish_scoped_artifact(self, record: ArtifactRecordV1) -> bool:
        async with self._runner.transaction() as connection:
            return await self._put_artifact_reference(connection, record)

    async def _publish_artifact(
        self, record: ArtifactRecordV1, publication_budget: Callable[[], float] | None
    ) -> bool:
        def check_commit_deadline(_connection: Connection) -> None:
            check_publication_budget(publication_budget)

        timeout = asyncio.timeout(check_publication_budget(publication_budget))
        try:
            async with timeout:
                async with self._runner._engine.begin() as connection:
                    if publication_budget is not None:
                        event.listen(
                            connection.sync_connection, "commit", check_commit_deadline
                        )
                    wrote = await self._put_artifact_reference(connection, record)
                    check_publication_budget(publication_budget)
        except TimeoutError:
            if timeout.expired():
                raise ArtifactPublicationDeadlineExceeded() from None
            raise
        return wrote

    async def _put_artifact_reference(
        self, connection: AsyncConnection, record: ArtifactRecordV1
    ) -> bool:
        reference_query = text(
            "SELECT content_hash, media_type, dependency_hashes, "
            "status, retention FROM fundamental.artifact_references "
            "WHERE artifact_id=:artifact_id"
        )
        key = {"artifact_id": record.artifact_id}
        existing = (await connection.execute(reference_query, key)).mappings().first()
        if existing is None:
            inserted = await connection.execute(
                text(
                    "INSERT INTO fundamental.artifact_references"
                    "(artifact_id, content_hash, media_type, dependency_hashes, "
                    "status, retention) "
                    "VALUES (:artifact_id, :content_hash, :media_type, "
                    "CAST(:dependency_hashes AS jsonb), :status, :retention) "
                    "ON CONFLICT (artifact_id) DO NOTHING RETURNING artifact_id"
                ),
                {
                    **key,
                    "content_hash": record.content_hash,
                    "media_type": record.media_type,
                    "dependency_hashes": json.dumps(record.dependency_hashes),
                    "status": record.status,
                    "retention": record.retention,
                },
            )
            wrote = inserted.scalar_one_or_none() is not None
            existing = (
                (await connection.execute(reference_query, key)).mappings().first()
            )
        else:
            wrote = False
        if existing is None or (
            existing["content_hash"] != record.content_hash
            or existing["media_type"] != record.media_type
            or tuple(existing["dependency_hashes"]) != record.dependency_hashes
            or existing["status"] != record.status
            or existing["retention"] != record.retention
        ):
            raise SnapshotError("ARTIFACT_ID_REUSED", "artifact IDs are immutable")
        return wrote

    def get_artifact(self, artifact_id: str) -> ArtifactRecordV1:
        self._require_ready()
        payload = self._runner.run(self._get_artifact_payload(artifact_id))
        if payload is None:
            raise SnapshotError(
                "ARTIFACT_NOT_FOUND", f"artifact {artifact_id} is unavailable"
            )
        return ArtifactRecordV1.model_validate_json(canonical_bytes(payload))

    def parser_action_result(self, action_key: str) -> str | None:
        """Read a disposable index; callers must verify its immutable evidence."""
        self._require_ready()
        return self._runner.run(self._parser_action_result(action_key))

    async def _parser_action_result(self, action_key: str) -> str | None:
        async with self._runner._engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT artifact_id FROM fundamental.parser_action_results "
                    "WHERE action_key=:key"
                ),
                {"key": action_key},
            )
            return result.scalar_one_or_none()

    def publish_parser_action_result(self, action_key: str, artifact_id: str) -> None:
        """Publish only after the owner has persisted the immutable result body."""
        self._require_ready()
        self._runner.run(self._publish_parser_action_result(action_key, artifact_id))

    async def _publish_parser_action_result(
        self, action_key: str, artifact_id: str
    ) -> None:
        async with self._runner.transaction() as connection:
            await connection.execute(
                text(
                    "INSERT INTO fundamental.parser_action_results(action_key, artifact_id) "
                    "VALUES (:key, :artifact_id) ON CONFLICT (action_key) DO UPDATE "
                    "SET artifact_id=EXCLUDED.artifact_id"
                ),
                {"key": action_key, "artifact_id": artifact_id},
            )

    def retained_artifact_records(
        self, artifact_ids: tuple[str, ...]
    ) -> dict[str, _RetainedArtifactMetadata]:
        self._require_ready()
        if not artifact_ids:
            return {}
        rows = self._runner.run(self._retained_artifact_records(artifact_ids))
        return {
            row["artifact_id"]: _RetainedArtifactMetadata(
                canonical_bytes(
                    {key: value for key, value in row.items() if key != "byte_length"}
                ),
                row["byte_length"],
            )
            for row in rows
        }

    async def _retained_artifact_records(
        self,
        artifact_ids: tuple[str, ...],
        connection: AsyncConnection | None = None,
    ) -> list[dict[str, Any]]:
        if connection is None:
            async with self._runner._engine.connect() as connection:
                return await self._retained_artifact_records(artifact_ids, connection)
        rows = await connection.execute(
            text(
                "SELECT artifact.artifact_id, artifact.content_hash, "
                "artifact.media_type, artifact.dependency_hashes, "
                "artifact.status, artifact.retention, content.byte_length "
                "FROM fundamental.artifact_references AS artifact "
                "LEFT JOIN fundamental.content_objects AS content "
                "ON artifact.content_hash=content.content_hash "
                "AND artifact.media_type=content.media_type "
                "WHERE artifact.artifact_id IN :artifact_ids"
            ).bindparams(bindparam("artifact_ids", expanding=True)),
            {"artifact_ids": artifact_ids},
        )
        return [dict(row) for row in rows.mappings()]

    def check_retained_artifact_journal(
        self,
        journal: BinaryIO,
        *,
        repair: tuple[str, str, int] | None = None,
    ) -> BinaryIO:
        self._require_ready()
        return self._runner.run(self._check_retained_artifact_journal(journal, repair))

    async def _check_retained_artifact_journal(
        self, journal: BinaryIO, repair: tuple[str, str, int] | None
    ) -> BinaryIO:
        replacement = tempfile.TemporaryFile() if repair is not None else None
        try:
            journal.seek(0)
            async with self._runner._engine.connect() as connection:
                connection = await connection.execution_options(
                    isolation_level="REPEATABLE READ"
                )
                async with connection.begin():
                    await connection.execute(text("SET TRANSACTION READ ONLY"))
                    for line in journal:
                        artifact_id, payload, byte_length = json.loads(line)
                        expected = (
                            _RetainedArtifactMetadata(payload.encode(), byte_length)
                            if payload is not None
                            else None
                        )
                        if (
                            repair is not None
                            and expected is not None
                            and expected.byte_length is None
                            and expected.references_content(repair[0], repair[1])
                        ):
                            byte_length = repair[2]
                            expected = _RetainedArtifactMetadata(
                                expected.payload, byte_length
                            )
                        rows = await self._retained_artifact_records(
                            (artifact_id,), connection
                        )
                        current = None
                        if rows:
                            row = rows[0]
                            current = _RetainedArtifactMetadata(
                                canonical_bytes(
                                    {k: v for k, v in row.items() if k != "byte_length"}
                                ),
                                row["byte_length"],
                            )
                        if current != expected:
                            raise DataReleaseError(
                                "ARTIFACT_EVIDENCE_CHANGED",
                                "release artifact metadata changed during its read operation",
                            )
                        if replacement is not None:
                            replacement.write(
                                canonical_bytes((artifact_id, payload, byte_length))
                                + b"\n"
                            )
            if replacement is not None:
                return replacement
            return journal
        except BaseException:
            if replacement is not None:
                replacement.close()
            raise

    async def _get_artifact_payload(self, artifact_id: str) -> dict[str, Any] | None:
        async with self._runner._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            "SELECT artifact_id, content_hash, media_type, "
                            "dependency_hashes, "
                            "status, retention FROM fundamental.artifact_references "
                            "WHERE artifact_id=:artifact_id"
                        ),
                        {"artifact_id": artifact_id},
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return {
            "artifact_id": row["artifact_id"],
            "content_hash": row["content_hash"],
            "media_type": row["media_type"],
            "dependency_hashes": tuple(row["dependency_hashes"]),
            "status": row["status"],
            "retention": row["retention"],
        }

    def _get_payload(self, table: str, key_column: str, key: str) -> dict[str, Any]:
        self._require_ready()
        payload = self._runner.run(self._get_payload_async(table, key_column, key))
        if payload is None:
            raise SnapshotError("SNAPSHOT_NOT_FOUND", f"{key} is unavailable")
        return payload

    async def _get_payload_async(
        self, table: str, key_column: str, key: str
    ) -> dict[str, Any] | None:
        async with self._runner._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            f"SELECT payload FROM {SCHEMA}.{table} "
                            f"WHERE {key_column}=:key"
                        ),
                        {"key": key},
                    )
                )
                .mappings()
                .first()
            )
        return None if row is None else dict(row["payload"])

    def _list_payloads(self, table: str) -> tuple[dict[str, Any], ...]:
        self._require_ready()
        return tuple(self._runner.run(self._list_payloads_async(table)))

    async def _list_payloads_async(self, table: str) -> list[dict[str, Any]]:
        async with self._runner._engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        text(f"SELECT payload FROM {SCHEMA}.{table}")
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row["payload"]) for row in rows]

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            try:
                self._runner.run(self._release_all_ingestion_locks(), cleanup=True)
            finally:
                self._runner.close()
                self._ready = False
                self._closed = True

    async def _release_all_ingestion_locks(self) -> None:
        held = tuple(self._ingestion_lock_connections.items())
        self._ingestion_lock_connections.clear()
        for _, (advisory_key, connection) in held:
            try:
                if not connection.closed:
                    await connection.execute(
                        text("SELECT pg_advisory_unlock(:advisory_key)"),
                        {"advisory_key": advisory_key},
                    )
                    await connection.commit()
            finally:
                await connection.close()


class _ReadOnlyFilesystemContentStore(FilesystemContentStore):
    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, content: bytes, *, media_type: str) -> str:
        raise SnapshotError(
            "READ_ONLY_STORAGE", "filesystem publication capability is unavailable"
        )


class PostgresContentStore:
    """Filesystem bytes with PostgreSQL content-object metadata."""

    def __init__(
        self, root: Path, metadata: PostgresMetadataStore, *, read_only: bool = False
    ) -> None:
        if read_only and not root.is_dir():
            raise SnapshotError(
                "SOURCE_BYTES_UNAVAILABLE", "read-only content root is missing"
            )
        if not read_only:
            try:
                root_stat = root.stat()
            except FileNotFoundError:
                pass
            else:
                if not S_ISDIR(root_stat.st_mode):
                    raise NotADirectoryError(
                        errno.ENOTDIR, "Not a directory", str(root)
                    )
        self._root = root
        self._filesystem_view: FilesystemContentStore | None = None
        self._metadata = metadata
        self._read_only = read_only

    @property
    def _filesystem(self) -> FilesystemContentStore:
        if self._filesystem_view is None:
            self._filesystem_view = (
                _ReadOnlyFilesystemContentStore(self._root)
                if self._read_only
                else FilesystemContentStore(self._root)
            )
        return self._filesystem_view

    def as_read_only(self) -> PostgresContentStore:
        return PostgresContentStore(self._root, self._metadata, read_only=True)

    def put(self, content: bytes, *, media_type: str) -> str:
        if self._read_only:
            raise SnapshotError(
                "READ_ONLY_STORAGE", "content publication capability is unavailable"
            )
        _check_metadata_budget()
        content_hash = self._filesystem.put(content, media_type=media_type)
        self._metadata.register_content(
            content_hash, media_type=media_type, byte_length=len(content)
        )
        return content_hash

    def get(self, content_hash: str, *, media_type: str) -> bytes:
        _check_metadata_budget()
        content = self._filesystem.get(content_hash, media_type=media_type)
        if self._read_only:
            if self._metadata.content_byte_length(
                content_hash, media_type=media_type
            ) != len(content):
                raise SnapshotError(
                    "CONTENT_METADATA_MISMATCH",
                    "retained content registration differs from its bytes",
                )
        else:
            self._metadata.register_content(
                content_hash, media_type=media_type, byte_length=len(content)
            )
        _check_metadata_budget()
        return content


class PostgresSnapshotRepository(SnapshotRepository):
    def __init__(self, metadata: PostgresMetadataStore) -> None:
        self._metadata = metadata

    def publish(self, snapshot: SourceSnapshotV1) -> None:
        self._metadata.publish_snapshot(snapshot)

    def get(self, snapshot_id: str) -> SourceSnapshotV1:
        return self._metadata.get_snapshot(snapshot_id)

    def find(
        self, *, identity: IdentityV1, valuation_timestamp: datetime
    ) -> tuple[SourceSnapshotV1, ...]:
        return tuple(
            sorted(
                (
                    snapshot
                    for snapshot in self._metadata.list_snapshots()
                    if snapshot.identity == identity
                    and snapshot.valuation_timestamp <= valuation_timestamp
                ),
                key=lambda item: (item.valuation_timestamp, item.snapshot_id),
                reverse=True,
            )
        )


class PostgresCanonicalFactRepository(CanonicalFactRepository):
    def __init__(self, metadata: PostgresMetadataStore) -> None:
        self._metadata = metadata

    def publish(self, fact: CanonicalFactV1) -> None:
        self._metadata.publish_fact(fact)

    def get(self, fact_id: str) -> CanonicalFactV1:
        return self._metadata.get_fact(fact_id)

    def list(self) -> tuple[CanonicalFactV1, ...]:
        return tuple(self._metadata.list_facts())

    def resolve(
        self,
        *,
        snapshot: SourceSnapshotV1 | IssuerOperatingSourceV1,
        valuation_timestamp: datetime,
        required_fields: tuple[str, ...],
    ) -> tuple[CanonicalFactV1, ...]:
        return resolve_canonical_facts(
            self._metadata.list_facts(),
            snapshot=snapshot,
            valuation_timestamp=valuation_timestamp,
            required_fields=required_fields,
        )


_SCOPED_ARTIFACT_READS: ContextVar[
    dict[tuple[PostgresMetadataStore, Path], _ScopedArtifactReads] | None
] = ContextVar("fiscal_scoped_artifact_reads", default=None)


@dataclass
class _ScopedArtifactReads:
    reader: _RetainedPostgresArtifactReads
    sealed: bool = False


class PostgresArtifactStore:
    """Artifact metadata in PostgreSQL and immutable bytes in the content volume."""

    def __init__(
        self,
        metadata: PostgresMetadataStore,
        content: PostgresContentStore,
        *,
        read_only: bool = False,
    ) -> None:
        self._metadata = metadata
        self._content = content.as_read_only() if read_only else content
        self._read_only = read_only

    def as_read_only(self) -> PostgresArtifactStore:
        return PostgresArtifactStore(self._metadata, self._content, read_only=True)

    def put(
        self,
        artifact_id: str,
        value: object,
        dependency_hashes: tuple[str, ...] = (),
        *,
        media_type: str = "application/json",
        retention: Literal["evidence", "operational_cache"] = "evidence",
    ) -> ArtifactRecordV1:
        return self.put_with_receipt(
            artifact_id,
            value,
            dependency_hashes,
            media_type=media_type,
            retention=retention,
        ).artifact

    def put_with_receipt(
        self,
        artifact_id: str,
        value: object,
        dependency_hashes: tuple[str, ...] = (),
        *,
        media_type: str = "application/json",
        retention: Literal["evidence", "operational_cache"] = "evidence",
        publication_budget: Callable[[], float] | None = None,
    ) -> ArtifactPublicationV1:
        return self.put_bytes_with_receipt(
            artifact_id,
            canonical_bytes(value),
            dependency_hashes,
            media_type=media_type,
            retention=retention,
            publication_budget=publication_budget,
        )

    def put_bytes_with_receipt(
        self,
        artifact_id: str,
        payload: bytes,
        dependency_hashes: tuple[str, ...] = (),
        *,
        media_type: str = "application/octet-stream",
        retention: Literal["evidence", "operational_cache"] = "evidence",
        publication_budget: Callable[[], float] | None = None,
    ) -> ArtifactPublicationV1:
        if self._read_only:
            raise SnapshotError(
                "READ_ONLY_STORAGE", "artifact publication capability is unavailable"
            )
        content_hash = hashlib.sha256(payload).hexdigest()
        record = ArtifactRecordV1(
            artifact_id=artifact_id,
            content_hash=content_hash,
            dependency_hashes=dependency_hashes,
            media_type=media_type,
            retention=retention,
        )
        try:
            previous = self._metadata.get_artifact(artifact_id)
        except SnapshotError as error:
            if error.code != "ARTIFACT_NOT_FOUND":
                raise
        else:
            if previous != record:
                raise SnapshotError("ARTIFACT_ID_REUSED", "artifact IDs are immutable")
            if self.read(artifact_id) != payload:
                raise SnapshotError(
                    "ARTIFACT_BYTES_UNAVAILABLE",
                    "published artifact bytes failed verification",
                )
            check_publication_budget(publication_budget)
            return ArtifactPublicationV1(artifact=previous, wrote=False)
        self._content.put(payload, media_type=media_type)
        wrote = self._metadata.publish_artifact(
            record, publication_budget=publication_budget
        )
        return ArtifactPublicationV1(artifact=record, wrote=wrote)

    def _scoped_reads(self) -> _ScopedArtifactReads | None:
        active = _SCOPED_ARTIFACT_READS.get()
        if not self._read_only or active is None:
            return None
        scoped = active.get((self._metadata, self._content._root.resolve()))
        if scoped is not None and scoped.sealed:
            raise RuntimeError("scoped artifact reads ended before final observation")
        return scoped

    @contextmanager
    def scoped_read_operation(self) -> Iterator[None]:
        if not self._read_only:
            raise SnapshotError(
                "READ_ONLY_STORAGE",
                "scoped fiscal reads require a read-only artifact store",
            )
        key = (self._metadata, self._content._root.resolve())
        active = _SCOPED_ARTIFACT_READS.get()
        if active is not None and key in active:
            self._scoped_reads()
            yield
            return
        reader = _RetainedPostgresArtifactReads(
            self, (), max_entries=512, max_bytes=2 * 1024 * 1024
        )
        scoped = _ScopedArtifactReads(reader)
        token = _SCOPED_ARTIFACT_READS.set({**(active or {}), key: scoped})
        try:
            yield
            if not scoped.sealed:
                reader.finish()
        finally:
            reader.close()
            _SCOPED_ARTIFACT_READS.reset(token)

    def seal_scoped_read_operation(self) -> None:
        scoped = self._scoped_reads()
        if scoped is not None:
            scoped.reader._require_current()
            scoped.sealed = True

    def get(self, artifact_id: str) -> ArtifactRecordV1:
        scoped = self._scoped_reads()
        return (
            scoped.reader.get(artifact_id)
            if scoped is not None
            else self._metadata.get_artifact(artifact_id)
        )

    def read(self, artifact_id: str) -> bytes:
        scoped = self._scoped_reads()
        if scoped is not None:
            return scoped.reader.read(artifact_id)
        record = self.get(artifact_id)
        return self._content.get(record.content_hash, media_type=record.media_type)

    @contextmanager
    def retained_read_operation(
        self,
        artifact_ids: tuple[str, ...],
        *,
        max_entries: int = 512,
        max_bytes: int = 2 * 1024 * 1024,
    ) -> Iterator[_RetainedPostgresArtifactReads]:
        if min(max_entries, max_bytes) < 0:
            raise ValueError("artifact metadata retention limits must be nonnegative")
        try:
            reader = _RetainedPostgresArtifactReads(
                self, artifact_ids, max_entries=max_entries, max_bytes=max_bytes
            )
        except Exception as error:
            raise DataReleaseError(
                "DATA_RELEASE_ARTIFACT_UNAVAILABLE",
                "release artifact metadata is unavailable",
            ) from error
        try:
            yield reader
        except BaseException:
            reader.close()
            raise
        else:
            try:
                reader.finish()
            except DataReleaseError:
                raise
            except Exception as error:
                raise DataReleaseError(
                    "DATA_RELEASE_ARTIFACT_UNAVAILABLE",
                    "release artifact metadata is unavailable",
                ) from error

    def has_content_hash(self, content_hash: str) -> bool:
        return self._metadata.has_content_hash(content_hash)

    def reset_operational_cache(self) -> None:
        return None


@dataclass(frozen=True, slots=True)
class _RetainedArtifactMetadata:
    payload: bytes
    byte_length: int | None

    def record(self) -> ArtifactRecordV1:
        return ArtifactRecordV1.model_validate_json(self.payload)

    def references_content(self, content_hash: str, media_type: str) -> bool:
        payload = json.loads(self.payload)
        return (
            payload["content_hash"] == content_hash
            and payload["media_type"] == media_type
        )


class _RetainedPostgresArtifactReads:
    """Metadata snapshot for one verification; bytes stay streamed and rehashed."""

    def __init__(
        self,
        artifacts: PostgresArtifactStore,
        artifact_ids: tuple[str, ...],
        *,
        max_entries: int,
        max_bytes: int,
    ) -> None:
        self._artifacts = artifacts
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._ids: set[str] = set()
        self._records: dict[str, _RetainedArtifactMetadata] = {}
        self._closed = False
        self._fallback = False
        self._journal: BinaryIO | None = None
        for artifact_id in artifact_ids:
            self._ids.add(artifact_id)
            if self._over_budget():
                self._discard_batch(artifact_ids)
                return
        self._records = artifacts._metadata.retained_artifact_records(
            tuple(sorted(self._ids))
        )
        if self._over_budget():
            self._discard_batch()

    def _over_budget(self) -> bool:
        retained_bytes = (
            sys.getsizeof(self._ids)
            + sys.getsizeof(self._records)
            + sum(sys.getsizeof(identity) for identity in self._ids)
            + sum(
                sys.getsizeof(identity)
                + sys.getsizeof(entry)
                + sys.getsizeof(entry.payload)
                + sys.getsizeof(entry.byte_length)
                for identity, entry in self._records.items()
            )
        )
        return len(self._ids) > self._max_entries or retained_bytes > self._max_bytes

    def _witness(
        self, artifact_id: str, entry: _RetainedArtifactMetadata | None
    ) -> None:
        assert self._journal is not None
        self._journal.write(
            canonical_bytes(
                (
                    artifact_id,
                    entry.payload.decode() if entry is not None else None,
                    entry.byte_length if entry is not None else None,
                )
            )
            + b"\n"
        )

    def _discard_batch(self, initial_ids: tuple[str, ...] | None = None) -> None:
        self._journal = tempfile.TemporaryFile()
        try:
            if initial_ids is not None:
                for artifact_id in initial_ids:
                    entry = self._artifacts._metadata.retained_artifact_records(
                        (artifact_id,)
                    ).get(artifact_id)
                    self._witness(artifact_id, entry)
            else:
                for artifact_id in self._ids:
                    self._witness(artifact_id, self._records.get(artifact_id))
        except BaseException:
            self.close()
            raise
        self._fallback = True
        self._ids.clear()
        self._records.clear()

    def _require_current(self) -> None:
        if self._journal is not None:
            self._artifacts._metadata.check_retained_artifact_journal(self._journal)
        else:
            current = self._artifacts._metadata.retained_artifact_records(
                tuple(sorted(self._ids))
            )
            if current != self._records:
                raise DataReleaseError(
                    "ARTIFACT_EVIDENCE_CHANGED",
                    "release artifact metadata changed during its read operation",
                )

    def get(self, artifact_id: str) -> ArtifactRecordV1:
        return self._entry(artifact_id).record()

    def _entry(self, artifact_id: str) -> _RetainedArtifactMetadata:
        if self._closed:
            raise RuntimeError("retained artifact read operation has ended")
        if self._fallback:
            entry = self._artifacts._metadata.retained_artifact_records(
                (artifact_id,)
            ).get(artifact_id)
            self._witness(artifact_id, entry)
            if entry is None:
                raise SnapshotError(
                    "ARTIFACT_NOT_FOUND", f"artifact {artifact_id} is unavailable"
                )
            return entry
        if artifact_id not in self._ids:
            if len(self._ids) >= self._max_entries:
                self._require_current()
                self._discard_batch()
                return self._entry(artifact_id)
            self._ids.add(artifact_id)
            self._records.update(
                self._artifacts._metadata.retained_artifact_records((artifact_id,))
            )
            if self._over_budget():
                self._require_current()
                self._discard_batch()
                return self._entry(artifact_id)
        entry = self._records.get(artifact_id)
        if entry is None:
            raise SnapshotError(
                "ARTIFACT_NOT_FOUND", f"artifact {artifact_id} is unavailable"
            )
        return entry

    def read(self, artifact_id: str) -> bytes:
        entry = self._entry(artifact_id)
        record = entry.record()
        raw = self._artifacts._content._filesystem.get(
            record.content_hash, media_type=record.media_type
        )
        if entry.byte_length is None:
            if self._artifacts._read_only:
                raise SnapshotError(
                    "CONTENT_REGISTRATION_UNAVAILABLE",
                    "read-only artifact verification cannot repair missing registration",
                )
            self._artifacts._metadata.register_content(
                record.content_hash, media_type=record.media_type, byte_length=len(raw)
            )
            if self._journal is not None:
                previous = self._journal
                self._journal = (
                    self._artifacts._metadata.check_retained_artifact_journal(
                        previous,
                        repair=(record.content_hash, record.media_type, len(raw)),
                    )
                )
                previous.close()
                return raw
            current = self._artifacts._metadata.retained_artifact_records(
                tuple(sorted(self._ids))
            )
            repaired = current.get(artifact_id)
            if repaired is None or repaired.payload != entry.payload:
                raise DataReleaseError(
                    "ARTIFACT_EVIDENCE_CHANGED",
                    "artifact metadata changed during content registration repair",
                )
            if repaired.byte_length != len(raw):
                raise SnapshotError(
                    "CONTENT_METADATA_MISMATCH",
                    "repaired content registration differs from its checked bytes",
                )
            expected = {
                identity: _RetainedArtifactMetadata(
                    previous.payload,
                    len(raw)
                    if previous.byte_length is None
                    and previous.references_content(
                        record.content_hash, record.media_type
                    )
                    else previous.byte_length,
                )
                for identity, previous in self._records.items()
            }
            if current != expected:
                raise DataReleaseError(
                    "ARTIFACT_EVIDENCE_CHANGED",
                    "artifact metadata changed during content registration repair",
                )
            self._records = expected
            entry = repaired
            if self._over_budget():
                self._require_current()
                self._discard_batch()
        if entry.byte_length != len(raw):
            raise SnapshotError(
                "CONTENT_METADATA_MISMATCH",
                "retained content registration differs from its checked bytes",
            )
        return raw

    def finish(self) -> None:
        try:
            self._require_current()
        finally:
            self.close()

    def close(self) -> None:
        self._closed = True
        self._ids.clear()
        self._records.clear()
        if self._journal is not None:
            self._journal.close()
            self._journal = None


__all__ = [
    "MetadataHealth",
    "PostgresArtifactStore",
    "PostgresCanonicalFactRepository",
    "PostgresContentStore",
    "PostgresMetadataStore",
    "PostgresSnapshotRepository",
    "SCHEMA_VERSION",
]
