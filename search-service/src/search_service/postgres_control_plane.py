from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import asyncpg
from cryptography.fernet import Fernet, InvalidToken

from .contracts import (
    ProviderKeySummary,
    ProviderPreference,
    ProviderSetting,
    SearchErrorCode,
    UserSettings,
)
from .errors import SearchServiceError


@dataclass(frozen=True)
class StoredCredential:
    key_id: str
    provider: str
    api_key: str
    enabled: bool
    priority: int
    fingerprint: str
    status: str
    provider_priority: int = 0
    key_priority: int = 0
    cooldown_until: datetime | None = None


class PostgresSearchControlPlane:
    def __init__(self, dsn: str, encryption_key: str) -> None:
        if not dsn or not encryption_key:
            raise ValueError("Search database URL and encryption key are required")
        try:
            self._cipher = Fernet(encryption_key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise ValueError(
                "SEARCH_PROVIDER_ENCRYPTION_KEY must be a Fernet key"
            ) from exc
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None
        self._init_lock = asyncio.Lock()

    async def _connection(self) -> asyncpg.Pool:
        async with self._init_lock:
            if self._pool is None:
                pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=10)
                async with pool.acquire() as connection:
                    await connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS search_provider_keys (
                            owner_id TEXT NOT NULL,
                            key_id TEXT NOT NULL,
                            provider TEXT NOT NULL,
                            encrypted_key TEXT NOT NULL,
                            label TEXT NOT NULL,
                            suffix TEXT NOT NULL,
                            fingerprint TEXT NOT NULL,
                            enabled BOOLEAN NOT NULL DEFAULT TRUE,
                            priority INTEGER NOT NULL DEFAULT 0 CHECK (priority >= 0),
                            status TEXT NOT NULL DEFAULT 'active',
                            failure_count INTEGER NOT NULL DEFAULT 0,
                            cooldown_until TIMESTAMPTZ,
                            last_tested_at TIMESTAMPTZ NOT NULL,
                            lease_until TIMESTAMPTZ,
                            last_used_at TIMESTAMPTZ,
                            PRIMARY KEY (owner_id, key_id),
                            UNIQUE (owner_id, provider, fingerprint)
                        )
                        """
                    )
                    # Existing development databases may have been created by
                    # the one-key schema. Keep this startup migration small and
                    # idempotent; production migrations can later own it.
                    await connection.execute(
                        """
                        ALTER TABLE search_provider_keys
                            DROP CONSTRAINT IF EXISTS search_provider_keys_owner_id_provider_key,
                            DROP CONSTRAINT IF EXISTS search_provider_keys_owner_id_priority_key;
                        ALTER TABLE search_provider_keys
                            ADD COLUMN IF NOT EXISTS lease_until TIMESTAMPTZ,
                            ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMPTZ;
                        CREATE UNIQUE INDEX IF NOT EXISTS
                            search_provider_keys_owner_provider_fingerprint_idx
                            ON search_provider_keys(owner_id, provider, fingerprint);
                        """
                    )
                    await connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS search_provider_preferences (
                            owner_id TEXT NOT NULL,
                            provider TEXT NOT NULL,
                            enabled BOOLEAN NOT NULL,
                            priority INTEGER NOT NULL CHECK (priority >= 0),
                            PRIMARY KEY (owner_id, provider),
                            UNIQUE (owner_id, priority)
                        )
                        """
                    )
                    await connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS search_provider_health (
                            owner_id TEXT NOT NULL,
                            provider TEXT NOT NULL,
                            failure_count INTEGER NOT NULL DEFAULT 0,
                            cooldown_until TIMESTAMPTZ,
                            PRIMARY KEY (owner_id, provider)
                        )
                        """
                    )
                self._pool = pool
            return self._pool

    async def aclose(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def is_ready(self) -> bool:
        pool = await self._connection()
        async with pool.acquire() as connection:
            result: int | None = await connection.fetchval("SELECT 1")
            return result == 1

    def _decrypt(self, encrypted: str) -> str:
        try:
            return self._cipher.decrypt(encrypted.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise RuntimeError(
                "stored provider credential cannot be decrypted"
            ) from exc

    @staticmethod
    def _summary(row: asyncpg.Record) -> ProviderKeySummary:
        priority = (
            row["key_priority"] if "key_priority" in row.keys() else row["priority"]
        )
        return ProviderKeySummary(
            id=row["key_id"],
            provider=row["provider"],
            label=row["label"],
            suffix=row["suffix"],
            fingerprint=row["fingerprint"],
            enabled=row["enabled"],
            priority=priority,
            status=row["status"],
            failure_count=row["failure_count"],
            cooldown_until=row["cooldown_until"],
            last_tested_at=row["last_tested_at"],
            last_used_at=row["last_used_at"],
        )

    @staticmethod
    def _credential(row: asyncpg.Record, api_key: str) -> StoredCredential:
        return StoredCredential(
            key_id=row["key_id"],
            provider=row["provider"],
            api_key=api_key,
            enabled=row["enabled"],
            priority=row["key_priority"],
            fingerprint=row["fingerprint"],
            status=row["status"],
            provider_priority=row["provider_priority"],
            key_priority=row["key_priority"],
            cooldown_until=row.get("cooldown_until") if hasattr(row, "get") else None,
        )

    async def credentials_for(self, *, subject_id: str) -> tuple[StoredCredential, ...]:
        pool = await self._connection()
        async with pool.acquire() as connection:
            await connection.execute(
                """UPDATE search_provider_keys SET status='active',cooldown_until=NULL
                WHERE owner_id=$1 AND status='cooldown' AND cooldown_until <= now()""",
                subject_id,
            )
            rows = await connection.fetch(
                """
                SELECT k.key_id,k.provider,k.encrypted_key,k.fingerprint,k.status,
                       k.enabled,k.priority AS key_priority,k.cooldown_until,
                       COALESCE(p.enabled,TRUE) AS provider_enabled,
                       COALESCE(p.priority,2147483647) AS provider_priority
                FROM search_provider_preferences p
                RIGHT JOIN search_provider_keys k
                  ON p.owner_id = k.owner_id AND p.provider = k.provider
                LEFT JOIN search_provider_health h
                  ON h.owner_id = k.owner_id AND h.provider = k.provider
                WHERE k.owner_id = $1
                  AND k.enabled
                  AND COALESCE(p.enabled,TRUE)
                  AND k.status = 'active'
                  AND (h.cooldown_until IS NULL OR h.cooldown_until <= now())
                  AND (k.cooldown_until IS NULL OR k.cooldown_until <= now())
                  AND (k.lease_until IS NULL OR k.lease_until <= now())
                ORDER BY provider_priority,k.provider,k.priority,k.key_id
                """,
                subject_id,
            )
        return tuple(
            self._credential(
                row,
                self._decrypt(row["encrypted_key"]) if row["encrypted_key"] else "",
            )
            for row in rows
        )

    async def claim_credential(
        self, *, subject_id: str, provider: str, lease_seconds: int = 30
    ) -> StoredCredential | None:
        if lease_seconds < 1 or lease_seconds > 300:
            raise ValueError("lease_seconds must be between 1 and 300")
        pool = await self._connection()
        async with pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                """
                SELECT k.key_id,k.provider,k.encrypted_key,k.fingerprint,k.status,
                       k.enabled,k.priority AS key_priority,k.cooldown_until,
                       COALESCE(p.priority,2147483647) AS provider_priority
                FROM search_provider_keys k
                LEFT JOIN search_provider_preferences p
                  ON p.owner_id=k.owner_id AND p.provider=k.provider
                LEFT JOIN search_provider_health h
                  ON h.owner_id=k.owner_id AND h.provider=k.provider
                WHERE k.owner_id=$1 AND k.provider=$2
                  AND k.enabled AND COALESCE(p.enabled,TRUE)
                  AND k.status='active'
                  AND (h.cooldown_until IS NULL OR h.cooldown_until <= now())
                  AND (k.cooldown_until IS NULL OR k.cooldown_until <= now())
                  AND (k.lease_until IS NULL OR k.lease_until <= now())
                ORDER BY k.priority,k.last_used_at NULLS FIRST,k.key_id
                FOR UPDATE OF k SKIP LOCKED
                LIMIT 1
                """,
                subject_id,
                provider,
            )
            if row is None:
                return None
            claimed = await connection.fetchrow(
                """
                UPDATE search_provider_keys
                   SET lease_until=now() + ($3::double precision * interval '1 second'),
                       last_used_at=now()
                 WHERE owner_id=$1 AND key_id=$2
                RETURNING key_id
                """,
                subject_id,
                row["key_id"],
                lease_seconds,
            )
            if claimed is None:
                return None
            return self._credential(row, self._decrypt(row["encrypted_key"]))

    async def _save_key(
        self,
        *,
        subject_id: str,
        provider: str,
        api_key: str,
        label: str,
        suffix: str,
        fingerprint: str,
        key_id: str,
        replace: bool,
    ) -> ProviderKeySummary:
        pool = await self._connection()
        encrypted = self._cipher.encrypt(api_key.encode("utf-8")).decode("ascii")
        now = datetime.now(UTC)
        async with pool.acquire() as connection, connection.transaction():
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext($1))", subject_id
            )
            if replace:
                existing = await connection.fetchrow(
                    "SELECT key_id FROM search_provider_keys WHERE owner_id=$1 AND key_id=$2 FOR UPDATE",
                    subject_id,
                    key_id,
                )
                if existing is None:
                    raise SearchServiceError(
                        SearchErrorCode.INVALID_REQUEST,
                        400,
                        "provider key was not found",
                    )
                row = await connection.fetchrow(
                    """UPDATE search_provider_keys SET provider=$3, encrypted_key=$4, label=$5,
                    suffix=$6, fingerprint=$7, status='active', failure_count=0,
                    cooldown_until=NULL, lease_until=NULL, last_used_at=NULL, last_tested_at=$8
                    WHERE owner_id=$1 AND key_id=$2 RETURNING *""",
                    subject_id,
                    key_id,
                    provider,
                    encrypted,
                    label,
                    suffix,
                    fingerprint,
                    now,
                )
            else:
                row = await connection.fetchrow(
                    """SELECT * FROM search_provider_keys
                    WHERE owner_id=$1 AND provider=$2 AND fingerprint=$3 FOR UPDATE""",
                    subject_id,
                    provider,
                    fingerprint,
                )
                if row is None:
                    priority = await connection.fetchval(
                        "SELECT COALESCE(MAX(priority)+1,0) FROM search_provider_keys WHERE owner_id=$1 AND provider=$2",
                        subject_id,
                        provider,
                    )
                    row = await connection.fetchrow(
                        """INSERT INTO search_provider_keys
                        (owner_id,key_id,provider,encrypted_key,label,suffix,fingerprint,priority,last_tested_at)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *""",
                        subject_id,
                        key_id,
                        provider,
                        encrypted,
                        label,
                        suffix,
                        fingerprint,
                        priority,
                        now,
                    )
            if row is None:
                raise RuntimeError("provider key write returned no row")
        return self._summary(row)

    async def add_tested_key(
        self,
        *,
        subject_id: str,
        provider: str,
        api_key: str,
        label: str,
        suffix: str,
        fingerprint: str,
    ) -> ProviderKeySummary:
        return await self._save_key(
            subject_id=subject_id,
            provider=provider,
            api_key=api_key,
            label=label,
            suffix=suffix,
            fingerprint=fingerprint,
            key_id=str(uuid.uuid4()),
            replace=False,
        )

    async def replace_tested_key(
        self,
        *,
        subject_id: str,
        provider: str,
        api_key: str,
        label: str,
        suffix: str,
        fingerprint: str,
        key_id: str,
    ) -> ProviderKeySummary:
        return await self._save_key(
            subject_id=subject_id,
            provider=provider,
            api_key=api_key,
            label=label,
            suffix=suffix,
            fingerprint=fingerprint,
            key_id=key_id,
            replace=True,
        )

    async def list_keys(self, *, subject_id: str) -> tuple[ProviderKeySummary, ...]:
        pool = await self._connection()
        async with pool.acquire() as connection:
            await connection.execute(
                """UPDATE search_provider_keys SET status='active',cooldown_until=NULL
                WHERE owner_id=$1 AND status='cooldown' AND cooldown_until <= now()""",
                subject_id,
            )
            rows = await connection.fetch(
                """SELECT k.key_id,k.provider,k.label,k.suffix,k.fingerprint,k.enabled,
                COALESCE(p.priority,k.priority) AS priority,k.status,k.failure_count,
                k.cooldown_until,k.last_tested_at,k.last_used_at
                FROM search_provider_keys k LEFT JOIN search_provider_preferences p
                ON p.owner_id=k.owner_id AND p.provider=k.provider
                WHERE k.owner_id=$1 ORDER BY COALESCE(p.priority,2147483647),k.provider,
                k.priority,k.key_id""",
                subject_id,
            )
        return tuple(self._summary(row) for row in rows)

    async def delete_key(self, *, subject_id: str, key_id: str) -> None:
        pool = await self._connection()
        async with pool.acquire() as connection:
            await connection.execute(
                "DELETE FROM search_provider_keys WHERE owner_id=$1 AND key_id=$2",
                subject_id,
                key_id,
            )

    async def record_provider_failure(
        self,
        *,
        subject_id: str,
        provider: str,
        cooldown_seconds: int = 30,
    ) -> None:
        if cooldown_seconds < 0 or cooldown_seconds > 3600:
            raise ValueError("cooldown_seconds must be between 0 and 3600")
        pool = await self._connection()
        async with pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO search_provider_health(owner_id,provider,failure_count,cooldown_until)
                VALUES ($1,$2,1,now() + ($3::double precision * interval '1 second'))
                ON CONFLICT (owner_id,provider) DO UPDATE
                SET failure_count=search_provider_health.failure_count+1,
                    cooldown_until=EXCLUDED.cooldown_until
                """,
                subject_id,
                provider,
                cooldown_seconds,
            )

    async def set_key_enabled(
        self, *, subject_id: str, key_id: str, enabled: bool
    ) -> ProviderKeySummary:
        pool = await self._connection()
        async with pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                """
                UPDATE search_provider_keys
                   SET enabled=$3,
                       status=CASE WHEN $3 THEN 'active' ELSE 'disabled' END,
                       cooldown_until=NULL,
                       lease_until=NULL,
                       failure_count=CASE WHEN $3 THEN 0 ELSE failure_count END
                 WHERE owner_id=$1 AND key_id=$2
                RETURNING key_id,provider,label,suffix,fingerprint,enabled,priority,status,
                          failure_count,cooldown_until,last_tested_at,last_used_at
                """,
                subject_id,
                key_id,
                enabled,
            )
            if row is None:
                raise SearchServiceError(
                    SearchErrorCode.INVALID_REQUEST,
                    404,
                    "provider key was not found",
                )
            return self._summary(row)

    async def get_settings(self, *, subject_id: str) -> UserSettings:
        pool = await self._connection()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """SELECT COALESCE(p.provider,k.provider) AS provider,
                COALESCE(p.enabled,TRUE) AS provider_enabled,
                COALESCE(p.priority,2147483647) AS provider_priority,
                k.key_id,k.label,k.suffix,k.fingerprint,k.enabled,k.priority,
                k.status,k.failure_count,k.cooldown_until,k.last_tested_at,k.last_used_at
                FROM search_provider_preferences p FULL OUTER JOIN search_provider_keys k
                ON p.owner_id=k.owner_id AND p.provider=k.provider
                WHERE COALESCE(p.owner_id,k.owner_id)=$1
                ORDER BY COALESCE(p.priority,2147483647),COALESCE(p.provider,k.provider),k.priority,k.key_id""",
                subject_id,
            )
        settings: dict[str, tuple[bool, int, list[ProviderKeySummary]]] = {}
        for row in rows:
            provider = row["provider"]
            item = settings.setdefault(
                provider,
                (row["provider_enabled"], row["provider_priority"], []),
            )
            if row["key_id"] is not None:
                item[2].append(self._summary(row))
        return UserSettings(
            providers=tuple(
                ProviderSetting(
                    provider=provider,
                    enabled=enabled,
                    priority=priority,
                    keys=tuple(keys),
                )
                for provider, (enabled, priority, keys) in settings.items()
            )
        )

    async def replace_settings(
        self, *, subject_id: str, providers: tuple[ProviderPreference, ...]
    ) -> UserSettings:
        pool = await self._connection()
        async with pool.acquire() as connection, connection.transaction():
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext($1))", subject_id
            )
            await connection.execute(
                "DELETE FROM search_provider_preferences WHERE owner_id=$1", subject_id
            )
            await connection.executemany(
                "INSERT INTO search_provider_preferences(owner_id,provider,enabled,priority) VALUES($1,$2,$3,$4)",
                [
                    (subject_id, item.provider, item.enabled, item.priority)
                    for item in providers
                ],
            )
        return await self.get_settings(subject_id=subject_id)

    async def record_failure(
        self,
        *,
        subject_id: str,
        provider: str,
        key_id: str | None = None,
        cooldown_seconds: int = 30,
    ) -> None:
        """Record a provider failure for legacy callers.

        New runtime code should use ``record_key_failure`` so one bad key does
        not quarantine the whole provider pool.
        """
        if key_id is not None:
            await self.record_key_failure(
                subject_id=subject_id,
                key_id=key_id,
                cooldown_seconds=cooldown_seconds,
            )
            return
        await self.record_provider_failure(
            subject_id=subject_id,
            provider=provider,
            cooldown_seconds=cooldown_seconds,
        )

    async def release_credential(
        self, *, subject_id: str, key_id: str, succeeded: bool = False
    ) -> None:
        pool = await self._connection()
        async with pool.acquire() as connection:
            if succeeded:
                await connection.execute(
                    """
                    UPDATE search_provider_keys
                       SET lease_until=NULL,status='active',failure_count=0,
                           cooldown_until=NULL
                     WHERE owner_id=$1 AND key_id=$2
                    """,
                    subject_id,
                    key_id,
                )
                await connection.execute(
                    """
                    UPDATE search_provider_health
                       SET failure_count=0,cooldown_until=NULL
                     WHERE owner_id=$1
                       AND provider=(SELECT provider FROM search_provider_keys
                                     WHERE owner_id=$1 AND key_id=$2)
                    """,
                    subject_id,
                    key_id,
                )
            else:
                await connection.execute(
                    "UPDATE search_provider_keys SET lease_until=NULL WHERE owner_id=$1 AND key_id=$2",
                    subject_id,
                    key_id,
                )

    async def record_key_failure(
        self,
        *,
        subject_id: str,
        key_id: str,
        status: str = "cooldown",
        cooldown_seconds: int = 30,
    ) -> None:
        if status not in {"active", "cooldown", "invalid", "disabled"}:
            raise ValueError("unsupported provider key status")
        if cooldown_seconds < 0 or cooldown_seconds > 3600:
            raise ValueError("cooldown_seconds must be between 0 and 3600")
        pool = await self._connection()
        async with pool.acquire() as connection:
            await connection.execute(
                """
                UPDATE search_provider_keys
                   SET failure_count=failure_count+1,
                       status=$3,
                       cooldown_until=CASE WHEN $3='cooldown'
                           THEN now() + ($4::double precision * interval '1 second')
                           ELSE NULL END,
                       lease_until=NULL
                 WHERE owner_id=$1 AND key_id=$2
                """,
                subject_id,
                key_id,
                status,
                cooldown_seconds,
            )

    async def clear_expired_cooldowns(self, *, subject_id: str) -> None:
        pool = await self._connection()
        async with pool.acquire() as connection:
            await connection.execute(
                """UPDATE search_provider_keys SET status='active',cooldown_until=NULL
                WHERE owner_id=$1 AND status='cooldown' AND cooldown_until <= now()""",
                subject_id,
            )
