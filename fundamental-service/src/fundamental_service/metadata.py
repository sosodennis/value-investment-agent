"""Fundamental-owned PostgreSQL metadata and content-backed repositories.

The domain remains synchronous and stateless per request.  This adapter owns a
small background event loop so repository calls can use SQLAlchemy's async
PostgreSQL engine without leaking async plumbing through the deterministic
calculator or the existing repository protocols.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from .contracts import (
    CanonicalFactV1,
    IdentityV1,
    ReleaseManifestV1,
    SecIngestionResponseV1,
    SourceSnapshotV1,
)
from .data_releases import (
    DATA_RELEASE_CAPABILITY,
    ActiveDataReleaseV1,
    ActiveDataReleaseWithManifestV1,
    DataReleaseActivationCommandV1,
    DataReleaseError,
    DataReleaseManifestV1,
    DataReleaseTrustRootsV1,
    DataReleaseVerificationV1,
    verify_data_release_candidate,
)
from .facts import (
    CanonicalFactRepository,
    CanonicalMappingV1,
    canonical_fact_digest,
    resolve_canonical_facts,
)
from .original_issuer import IssuerOperatingSourceV1
from .policies import ModelSpecV1, PolicyRecordV1
from .replay import ArtifactPublicationV1, ArtifactRecordV1
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError, SnapshotRepository

SCHEMA = "fundamental"
SCHEMA_VERSION = "fundamental-metadata-v2"


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

    def run(self, coroutine: Any) -> Any:
        if not self._thread.is_alive():
            raise RuntimeError("database event loop is unavailable")
        future: Future[Any] = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        return future.result(timeout=15)

    def close(self) -> None:
        if self._thread.is_alive():
            try:
                self.run(self._engine.dispose())
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
    def health(self) -> MetadataHealth:
        return self._health

    @property
    def data_release_trust_roots_configured(self) -> bool:
        return self._data_release_trust_roots is not None

    def start(self) -> None:
        try:
            self._runner.run(self._startup())
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
                for statement in sql.split(";"):
                    statement = statement.strip()
                    if statement:
                        await connection.execute(text(statement))

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
        return self._runner.run(self._try_acquire_ingestion_lock(advisory_key))

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
        async with self._runner._engine.begin() as connection:
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
        self, advisory_key: int
    ) -> IngestionLockLease | None:
        connection = await self._runner._engine.connect()
        try:
            result = await connection.execute(
                text("SELECT pg_try_advisory_lock(:advisory_key)"),
                {"advisory_key": advisory_key},
            )
            acquired = bool(result.scalar_one())
            await connection.commit()
            if not acquired:
                await connection.close()
                return None
            lease = IngestionLockLease(uuid4().hex, advisory_key)
            self._ingestion_lock_connections[lease.lease_id] = (
                advisory_key,
                connection,
            )
            return lease
        except Exception:
            await connection.close()
            raise

    def release_ingestion_lock(self, lease: IngestionLockLease) -> None:
        self._runner.run(self._release_ingestion_lock(lease.lease_id))

    async def _release_ingestion_lock(self, lease_id: str) -> None:
        held = self._ingestion_lock_connections.pop(lease_id, None)
        if held is None:
            return
        advisory_key, connection = held
        try:
            if not connection.closed:
                await connection.execute(
                    text("SELECT pg_advisory_unlock(:advisory_key)"),
                    {"advisory_key": advisory_key},
                )
                await connection.commit()
        finally:
            await connection.close()

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
        manifest: DataReleaseManifestV1,
        verification: DataReleaseVerificationV1,
    ) -> None:
        self._require_data_release_capability()
        if self._data_release_trust_roots is None:
            raise DataReleaseError(
                "DATA_RELEASE_TRUST_ROOTS_UNCONFIGURED",
                "data release trust roots are required to publish a candidate",
            )
        verify_data_release_candidate(
            manifest, verification, self._data_release_trust_roots
        )
        self._runner.run(self._publish_data_release_candidate(manifest, verification))

    async def _publish_data_release_candidate(
        self,
        manifest: DataReleaseManifestV1,
        verification: DataReleaseVerificationV1,
    ) -> None:
        async with self._runner._engine.begin() as connection:
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

    def get_active_data_release(self, profile_id: str) -> ActiveDataReleaseV1 | None:
        self._require_data_release_capability()
        return self._runner.run(self._get_active_data_release(profile_id))

    def get_data_release_manifest(
        self, manifest_digest: str
    ) -> DataReleaseManifestV1 | None:
        self._require_data_release_capability()
        return self._runner.run(self._get_data_release_manifest(manifest_digest))

    async def _get_data_release_manifest(
        self, manifest_digest: str
    ) -> DataReleaseManifestV1 | None:
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
        return DataReleaseManifestV1.model_validate_json(canonical_bytes(payload))

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
    ) -> ActiveDataReleaseWithManifestV1 | None:
        self._require_data_release_capability()
        return self._runner.run(self._get_active_data_release_with_manifest(profile_id))

    async def _get_active_data_release_with_manifest(
        self, profile_id: str
    ) -> ActiveDataReleaseWithManifestV1 | None:
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
        manifest = DataReleaseManifestV1.model_validate_json(
            canonical_bytes(row["payload"])
        )
        return ActiveDataReleaseWithManifestV1(active=active, manifest=manifest)

    def compare_and_swap_data_release(
        self, command: DataReleaseActivationCommandV1
    ) -> ActiveDataReleaseV1:
        self._require_data_release_capability()
        return self._runner.run(self._compare_and_swap_data_release(command))

    async def _compare_and_swap_data_release(
        self, command: DataReleaseActivationCommandV1
    ) -> ActiveDataReleaseV1:
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

            candidate = (
                (
                    await connection.execute(
                        text(
                            "SELECT manifest.profile_id "
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
        async with self._runner._engine.begin() as connection:
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

    def publish_artifact(self, record: ArtifactRecordV1) -> bool:
        self._require_ready()
        return bool(self._runner.run(self._publish_artifact(record)))

    async def _publish_artifact(self, record: ArtifactRecordV1) -> bool:
        async with self._runner._engine.begin() as connection:
            existing = (
                (
                    await connection.execute(
                        text(
                            "SELECT content_hash, media_type, dependency_hashes, "
                            "status, retention FROM fundamental.artifact_references "
                            "WHERE artifact_id=:artifact_id"
                        ),
                        {"artifact_id": record.artifact_id},
                    )
                )
                .mappings()
                .first()
            )
            if existing is not None:
                if (
                    existing["content_hash"] != record.content_hash
                    or existing["media_type"] != record.media_type
                    or tuple(existing["dependency_hashes"]) != record.dependency_hashes
                    or existing["status"] != record.status
                    or existing["retention"] != record.retention
                ):
                    raise SnapshotError(
                        "ARTIFACT_ID_REUSED", "artifact IDs are immutable"
                    )
                return False
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
                    "artifact_id": record.artifact_id,
                    "content_hash": record.content_hash,
                    "media_type": record.media_type,
                    "dependency_hashes": json.dumps(record.dependency_hashes),
                    "status": record.status,
                    "retention": record.retention,
                },
            )
            existing = (
                (
                    await connection.execute(
                        text(
                            "SELECT content_hash, media_type, dependency_hashes, "
                            "status, retention FROM fundamental.artifact_references "
                            "WHERE artifact_id=:artifact_id"
                        ),
                        {"artifact_id": record.artifact_id},
                    )
                )
                .mappings()
                .first()
            )
            if existing is None or (
                existing["content_hash"] != record.content_hash
                or existing["media_type"] != record.media_type
                or tuple(existing["dependency_hashes"]) != record.dependency_hashes
                or existing["status"] != record.status
                or existing["retention"] != record.retention
            ):
                raise SnapshotError("ARTIFACT_ID_REUSED", "artifact IDs are immutable")
            return inserted.scalar_one_or_none() is not None

    def get_artifact(self, artifact_id: str) -> ArtifactRecordV1:
        self._require_ready()
        payload = self._runner.run(self._get_artifact_payload(artifact_id))
        if payload is None:
            raise SnapshotError(
                "ARTIFACT_NOT_FOUND", f"artifact {artifact_id} is unavailable"
            )
        return ArtifactRecordV1.model_validate_json(canonical_bytes(payload))

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
                self._runner.run(self._release_all_ingestion_locks())
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


class PostgresContentStore:
    """Filesystem bytes with PostgreSQL content-object metadata."""

    def __init__(self, root: Path, metadata: PostgresMetadataStore) -> None:
        from .snapshots import FilesystemContentStore

        self._filesystem = FilesystemContentStore(root)
        self._metadata = metadata

    def put(self, content: bytes, *, media_type: str) -> str:
        content_hash = self._filesystem.put(content, media_type=media_type)
        self._metadata.register_content(
            content_hash, media_type=media_type, byte_length=len(content)
        )
        return content_hash

    def get(self, content_hash: str, *, media_type: str) -> bytes:
        content = self._filesystem.get(content_hash, media_type=media_type)
        self._metadata.register_content(
            content_hash, media_type=media_type, byte_length=len(content)
        )
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


class PostgresArtifactStore:
    """Artifact metadata in PostgreSQL and immutable bytes in the content volume."""

    def __init__(
        self, metadata: PostgresMetadataStore, content: PostgresContentStore
    ) -> None:
        self._metadata = metadata
        self._content = content

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
    ) -> ArtifactPublicationV1:
        return self.put_bytes_with_receipt(
            artifact_id,
            canonical_bytes(value),
            dependency_hashes,
            media_type=media_type,
            retention=retention,
        )

    def put_bytes_with_receipt(
        self,
        artifact_id: str,
        payload: bytes,
        dependency_hashes: tuple[str, ...] = (),
        *,
        media_type: str = "application/octet-stream",
        retention: Literal["evidence", "operational_cache"] = "evidence",
    ) -> ArtifactPublicationV1:
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
            return ArtifactPublicationV1(artifact=previous, wrote=False)
        self._content.put(payload, media_type=media_type)
        wrote = self._metadata.publish_artifact(record)
        return ArtifactPublicationV1(artifact=record, wrote=wrote)

    def get(self, artifact_id: str) -> ArtifactRecordV1:
        return self._metadata.get_artifact(artifact_id)

    def read(self, artifact_id: str) -> bytes:
        record = self.get(artifact_id)
        return self._content.get(record.content_hash, media_type=record.media_type)

    def has_content_hash(self, content_hash: str) -> bool:
        return self._metadata.has_content_hash(content_hash)

    def reset_operational_cache(self) -> None:
        return None


__all__ = [
    "MetadataHealth",
    "PostgresArtifactStore",
    "PostgresCanonicalFactRepository",
    "PostgresContentStore",
    "PostgresMetadataStore",
    "PostgresSnapshotRepository",
    "SCHEMA_VERSION",
]
