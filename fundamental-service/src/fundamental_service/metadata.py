"""Fundamental-owned PostgreSQL metadata and content-backed repositories.

The domain remains synchronous and stateless per request.  This adapter owns a
small background event loop so repository calls can use SQLAlchemy's async
PostgreSQL engine without leaking async plumbing through the deterministic
calculator or the existing repository protocols.
"""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from pathlib import Path
from threading import Event, Thread
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from .contracts import CanonicalFactV1, IdentityV1, ReleaseManifestV1, SourceSnapshotV1
from .facts import (
    CanonicalFactRepository,
    CanonicalMappingV1,
    resolve_canonical_facts,
)
from .policies import ModelSpecV1, PolicyRecordV1
from .replay import ArtifactRecordV1
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError, SnapshotRepository

SCHEMA = "fundamental"
SCHEMA_VERSION = "fundamental-metadata-v1"


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


class PostgresMetadataStore:
    """Append-only metadata registry owned by the Fundamental service."""

    def __init__(
        self,
        database_url: str,
        *,
        auto_migrate: bool = False,
        schema: str = SCHEMA,
    ) -> None:
        if schema != SCHEMA:
            raise ValueError("Fundamental metadata must use the fundamental schema")
        self.schema = schema
        self.auto_migrate = auto_migrate
        self._runner = _AsyncRunner(database_url)
        self._ready = False
        self._health = MetadataHealth(False, None)

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def health(self) -> MetadataHealth:
        return self._health

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
        self._ready = True
        self._health = MetadataHealth(True, version)

    async def _apply_migration(self) -> None:
        migration = resources.files("fundamental_service").joinpath(
            "migrations/001_initial.sql"
        )
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
                    "ORDER BY applied_at DESC LIMIT 1"
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

    def publish_fact(self, fact: CanonicalFactV1) -> None:
        self._require_ready()
        self._runner.run(
            self._immutable_put(
                table="canonical_facts",
                key_column="fact_id",
                key=fact.fact_id,
                digest_column="fact_digest",
                digest=sha256_digest(fact.model_dump(mode="json")),
                payload=fact.model_dump(mode="json"),
            )
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

    def publish_artifact(self, record: ArtifactRecordV1) -> None:
        self._require_ready()
        self._runner.run(self._publish_artifact(record))

    async def _publish_artifact(self, record: ArtifactRecordV1) -> None:
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
                ):
                    raise SnapshotError(
                        "ARTIFACT_ID_REUSED", "artifact IDs are immutable"
                    )
                return
            await connection.execute(
                text(
                    "INSERT INTO fundamental.artifact_references"
                    "(artifact_id, content_hash, media_type, dependency_hashes, "
                    "status, retention) "
                    "VALUES (:artifact_id, :content_hash, :media_type, "
                    "CAST(:dependency_hashes AS jsonb), :status, :retention) "
                    "ON CONFLICT (artifact_id) DO NOTHING"
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
            ):
                raise SnapshotError("ARTIFACT_ID_REUSED", "artifact IDs are immutable")

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
        self._runner.close()
        self._ready = False


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

    def resolve(
        self,
        *,
        snapshot: SourceSnapshotV1,
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
        payload = canonical_bytes(value)
        content_hash = self._content.put(payload, media_type=media_type)
        record = ArtifactRecordV1(
            artifact_id=artifact_id,
            content_hash=content_hash,
            dependency_hashes=dependency_hashes,
            media_type=media_type,
            retention=retention,
        )
        self._metadata.publish_artifact(record)
        return record

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
