from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

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
    provider: str
    api_key: str
    enabled: bool
    priority: int


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
                            PRIMARY KEY (owner_id, key_id),
                            UNIQUE (owner_id, provider),
                            UNIQUE (owner_id, priority)
                        )
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
        return ProviderKeySummary(
            id=row["key_id"],
            provider=row["provider"],
            label=row["label"],
            suffix=row["suffix"],
            fingerprint=row["fingerprint"],
            enabled=row["enabled"],
            priority=row["priority"],
            status=row["status"],
            failure_count=row["failure_count"],
            cooldown_until=row["cooldown_until"],
            last_tested_at=row["last_tested_at"],
        )

    async def credentials_for(self, *, subject_id: str) -> tuple[StoredCredential, ...]:
        pool = await self._connection()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT COALESCE(p.provider,k.provider) AS provider, k.encrypted_key,
                       COALESCE(p.enabled,k.enabled,TRUE) AS enabled,
                       COALESCE(p.priority,k.priority,0) AS priority
                FROM search_provider_preferences p
                FULL JOIN search_provider_keys k
                  ON p.owner_id = k.owner_id AND p.provider = k.provider
                WHERE COALESCE(p.owner_id,k.owner_id) = $1
                  AND (k.cooldown_until IS NULL OR k.cooldown_until <= now())
                ORDER BY COALESCE(p.priority,k.priority,0), COALESCE(p.provider,k.provider)
                """,
                subject_id,
            )
        return tuple(
            StoredCredential(
                row["provider"],
                self._decrypt(row["encrypted_key"]) if row["encrypted_key"] else "",
                row["enabled"],
                row["priority"],
            )
            for row in rows
        )

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
                    cooldown_until=NULL, last_tested_at=$8
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
                priority = await connection.fetchval(
                    "SELECT COALESCE(MAX(priority)+1,0) FROM search_provider_keys WHERE owner_id=$1",
                    subject_id,
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
                WHERE owner_id=$1 AND cooldown_until <= now()""",
                subject_id,
            )
            rows = await connection.fetch(
                """SELECT k.key_id,k.provider,k.label,k.suffix,k.fingerprint,k.enabled,
                COALESCE(p.priority,k.priority) AS priority,k.status,k.failure_count,
                k.cooldown_until,k.last_tested_at
                FROM search_provider_keys k LEFT JOIN search_provider_preferences p
                ON p.owner_id=k.owner_id AND p.provider=k.provider
                WHERE k.owner_id=$1 ORDER BY COALESCE(p.priority,k.priority),k.provider""",
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

    async def get_settings(self, *, subject_id: str) -> UserSettings:
        pool = await self._connection()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """SELECT p.provider,p.enabled,p.priority,k.key_id,k.label,k.suffix,k.fingerprint,
                k.status,k.failure_count,k.cooldown_until,k.last_tested_at
                FROM search_provider_preferences p LEFT JOIN search_provider_keys k
                ON k.owner_id=p.owner_id AND k.provider=p.provider
                WHERE p.owner_id=$1 ORDER BY p.priority""",
                subject_id,
            )
        keys = {row["provider"]: self._summary(row) for row in rows if row["key_id"]}
        return UserSettings(
            providers=tuple(
                ProviderSetting(
                    provider=row["provider"],
                    enabled=row["enabled"],
                    priority=row["priority"],
                    key=keys.get(row["provider"]),
                )
                for row in rows
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
            rows = await connection.fetch(
                """SELECT p.provider,p.enabled,p.priority,k.key_id,k.label,k.suffix,k.fingerprint,
                k.status,k.failure_count,k.cooldown_until,k.last_tested_at
                FROM search_provider_preferences p LEFT JOIN search_provider_keys k
                ON k.owner_id=p.owner_id AND k.provider=p.provider
                WHERE p.owner_id=$1 ORDER BY p.priority""",
                subject_id,
            )
        keys = {row["provider"]: self._summary(row) for row in rows if row["key_id"]}
        return UserSettings(
            providers=tuple(
                ProviderSetting(
                    provider=row["provider"],
                    enabled=row["enabled"],
                    priority=row["priority"],
                    key=keys.get(row["provider"]),
                )
                for row in rows
            )
        )

    async def record_failure(
        self, *, subject_id: str, provider: str, cooldown_seconds: int = 30
    ) -> None:
        pool = await self._connection()
        until = datetime.now(UTC) + timedelta(seconds=cooldown_seconds)
        async with pool.acquire() as connection:
            await connection.execute(
                """UPDATE search_provider_keys SET failure_count=failure_count+1,
                status='cooldown', cooldown_until=$3 WHERE owner_id=$1 AND provider=$2""",
                subject_id,
                provider,
                until,
            )

    async def clear_expired_cooldowns(self, *, subject_id: str) -> None:
        pool = await self._connection()
        async with pool.acquire() as connection:
            await connection.execute(
                """UPDATE search_provider_keys SET status='active',cooldown_until=NULL
                WHERE owner_id=$1 AND cooldown_until <= now()""",
                subject_id,
            )
