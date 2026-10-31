from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String, delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _database_url() -> str:
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    database = os.getenv("POSTGRES_DB", "langgraph")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"


@dataclass(frozen=True)
class ProviderDeployment:
    id: str
    user_id: str
    label: str
    suffix: str
    fingerprint: str
    model: str
    created_at: str
    status: str
    failure_count: int
    cooldown_until: str | None
    last_tested_at: str | None
    last_used_at: str | None
    replacement_retire_at: str | None


class ProviderState:
    def __init__(self, *, encryption_key: str | None = None) -> None:
        self._engine = create_async_engine(_database_url(), pool_pre_ping=True)
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)
        self._cipher: Fernet | None = None
        if encryption_key:
            try:
                self._cipher = Fernet(encryption_key.encode("ascii"))
            except (ValueError, UnicodeEncodeError) as exc:
                raise ValueError(
                    "LLM_PROVIDER_ENCRYPTION_KEY must be a Fernet key"
                ) from exc

    async def initialize(self) -> None:
        async with self._engine.begin() as connection:
            # Multiple replicas can start against the same database. Serialize
            # schema creation and compatibility seeding so PostgreSQL does not
            # race while creating the same relation type.
            await connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                {"lock_key": "llm-provider-schema-initialize"},
            )
            await connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS llm_provider_owned_keys (
                        key_id VARCHAR(255) PRIMARY KEY,
                        user_id VARCHAR(256) NOT NULL,
                        fingerprint VARCHAR(128),
                        UNIQUE (user_id, fingerprint)
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS llm_provider_settings (
                        id VARCHAR(80) PRIMARY KEY,
                        value VARCHAR(200) NOT NULL,
                        updated_by VARCHAR(256) NOT NULL,
                        updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS llm_provider_deployments (
                        id VARCHAR(255) PRIMARY KEY,
                        user_id VARCHAR(256) NOT NULL,
                        encrypted_key TEXT NOT NULL,
                        label VARCHAR(255) NOT NULL,
                        suffix VARCHAR(16) NOT NULL,
                        fingerprint VARCHAR(128) NOT NULL,
                        model VARCHAR(512) NOT NULL,
                        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                        status VARCHAR(32) NOT NULL DEFAULT 'healthy',
                        failure_count INTEGER NOT NULL DEFAULT 0,
                        cooldown_until TIMESTAMP WITH TIME ZONE,
                        last_tested_at TIMESTAMP WITH TIME ZONE,
                        last_used_at TIMESTAMP WITH TIME ZONE,
                        replacement_retire_at TIMESTAMP WITH TIME ZONE,
                        UNIQUE (user_id, fingerprint)
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF to_regclass('public.auth_owned_resources') IS NOT NULL THEN
                            INSERT INTO llm_provider_owned_keys (key_id, user_id)
                            SELECT resource_id, user_id
                            FROM auth_owned_resources
                            WHERE resource_type = 'provider_key'
                            ON CONFLICT (key_id) DO NOTHING;
                        END IF;
                        IF to_regclass('public.llm_settings') IS NOT NULL THEN
                            INSERT INTO llm_provider_settings (id, value, updated_by)
                            SELECT 'selected_model', value, updated_by
                            FROM llm_settings
                            WHERE id = 'selected_model'
                            ON CONFLICT (id) DO NOTHING;
                        END IF;
                    END $$
                    """
                )
            )

    async def close(self) -> None:
        await self._engine.dispose()

    def _require_cipher(self) -> Fernet:
        if self._cipher is None:
            raise RuntimeError("LLM_PROVIDER_ENCRYPTION_KEY is required")
        return self._cipher

    async def list_deployments(self) -> list[ProviderDeployment]:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT id,user_id,label,suffix,fingerprint,model,created_at,
                               status,failure_count,cooldown_until,last_tested_at,
                               last_used_at,replacement_retire_at
                        FROM llm_provider_deployments
                        ORDER BY created_at,id
                        """
                    )
                )
            ).mappings()
            return [_deployment_from_row(row) for row in rows]

    async def get_deployment(self, deployment_id: str) -> ProviderDeployment | None:
        async with self._sessions() as session:
            row = (
                (
                    await session.execute(
                        text(
                            """
                        SELECT id,user_id,label,suffix,fingerprint,model,created_at,
                               status,failure_count,cooldown_until,last_tested_at,
                               last_used_at,replacement_retire_at
                        FROM llm_provider_deployments WHERE id=:id
                        """
                        ),
                        {"id": deployment_id},
                    )
                )
                .mappings()
                .first()
            )
            return _deployment_from_row(row) if row is not None else None

    async def find_deployment_by_fingerprint(
        self, *, user_id: str, fingerprint: str
    ) -> ProviderDeployment | None:
        async with self._sessions() as session:
            row = (
                (
                    await session.execute(
                        text(
                            """
                        SELECT id,user_id,label,suffix,fingerprint,model,created_at,
                               status,failure_count,cooldown_until,last_tested_at,
                               last_used_at,replacement_retire_at
                        FROM llm_provider_deployments
                        WHERE user_id=:user_id AND fingerprint=:fingerprint
                        """
                        ),
                        {"user_id": user_id, "fingerprint": fingerprint},
                    )
                )
                .mappings()
                .first()
            )
            return _deployment_from_row(row) if row is not None else None

    async def deployment_key(self, deployment_id: str) -> str:
        cipher = self._require_cipher()
        async with self._sessions() as session:
            encrypted = (
                await session.execute(
                    text(
                        "SELECT encrypted_key FROM llm_provider_deployments WHERE id=:id"
                    ),
                    {"id": deployment_id},
                )
            ).scalar_one_or_none()
        if not isinstance(encrypted, str):
            raise KeyError("provider deployment was not found")
        try:
            return cipher.decrypt(encrypted.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise RuntimeError(
                "provider deployment key could not be decrypted"
            ) from exc

    async def create_deployment(
        self,
        *,
        user_id: str,
        key: str,
        label: str,
        suffix: str,
        fingerprint: str,
        model: str,
        deployment_id: str | None = None,
    ) -> ProviderDeployment:
        cipher = self._require_cipher()
        identifier = deployment_id or str(uuid4())
        now = datetime.now(UTC)
        async with self._sessions() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO llm_provider_deployments
                    (id,user_id,encrypted_key,label,suffix,fingerprint,model,created_at,
                     status,last_tested_at)
                    VALUES (:id,:user_id,:encrypted_key,:label,:suffix,:fingerprint,
                            :model,:created_at,'healthy',:created_at)
                    """
                ),
                {
                    "id": identifier,
                    "user_id": user_id,
                    "encrypted_key": cipher.encrypt(key.encode("utf-8")).decode(
                        "ascii"
                    ),
                    "label": label,
                    "suffix": suffix,
                    "fingerprint": fingerprint,
                    "model": model,
                    "created_at": now,
                },
            )
            await session.commit()
        result = await self.get_deployment(identifier)
        if result is None:
            raise RuntimeError("provider deployment was not persisted")
        return result

    async def update_deployment(self, deployment_id: str, **values: object) -> None:
        allowed = {
            "model",
            "status",
            "failure_count",
            "cooldown_until",
            "last_tested_at",
            "last_used_at",
            "replacement_retire_at",
        }
        updates = {key: value for key, value in values.items() if key in allowed}
        if not updates:
            return
        assignments = ", ".join(f"{key}=:{key}" for key in updates)
        async with self._sessions() as session:
            await session.execute(
                text(f"UPDATE llm_provider_deployments SET {assignments} WHERE id=:id"),
                {**updates, "id": deployment_id},
            )
            await session.commit()

    async def delete_deployment(self, deployment_id: str) -> None:
        async with self._sessions() as session:
            await session.execute(
                text("DELETE FROM llm_provider_deployments WHERE id=:id"),
                {"id": deployment_id},
            )
            await session.execute(
                delete(_OwnedKey).where(_OwnedKey.key_id == deployment_id)
            )
            await session.commit()

    async def update_all_deployment_models(self, model: str) -> None:
        async with self._sessions() as session:
            await session.execute(
                text("UPDATE llm_provider_deployments SET model=:model"),
                {"model": model},
            )
            await session.commit()

    @asynccontextmanager
    async def replacement_lock(
        self, *, user_id: str, key_id: str
    ) -> AsyncIterator[None]:
        lock_key = f"llm-provider-replacement:{user_id}:{key_id}"
        async with self._engine.connect() as connection:
            await connection.execute(
                text("SELECT pg_advisory_lock(hashtextextended(:lock_key, 0))"),
                {"lock_key": lock_key},
            )
            try:
                yield
            finally:
                await connection.execute(
                    text("SELECT pg_advisory_unlock(hashtextextended(:lock_key, 0))"),
                    {"lock_key": lock_key},
                )

    async def claim(
        self,
        *,
        user_id: str,
        resource_type: str,
        resource_id: str,
        fingerprint: str | None = None,
    ) -> bool:
        _ = resource_type
        async with self._sessions() as session:
            session.add(
                _OwnedKey(
                    key_id=resource_id,
                    user_id=user_id,
                    fingerprint=fingerprint,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                row = await session.get(_OwnedKey, resource_id)
                return row is not None and row.user_id == user_id
        return True

    async def owns(self, *, user_id: str, resource_type: str, resource_id: str) -> bool:
        _ = resource_type
        async with self._sessions() as session:
            row = await session.get(_OwnedKey, resource_id)
            return row is not None and row.user_id == user_id

    async def owned_ids(self, *, user_id: str, resource_type: str) -> set[str]:
        _ = resource_type
        async with self._sessions() as session:
            result = await session.execute(
                select(_OwnedKey.key_id).where(_OwnedKey.user_id == user_id)
            )
            return set(result.scalars().all())

    async def find_by_fingerprint(
        self, *, user_id: str, fingerprint: str
    ) -> str | None:
        async with self._sessions() as session:
            result = await session.execute(
                select(_OwnedKey.key_id)
                .where(_OwnedKey.user_id == user_id)
                .where(_OwnedKey.fingerprint == fingerprint)
            )
            return result.scalar_one_or_none()

    async def release(self, *, resource_type: str, resource_id: str) -> None:
        _ = resource_type
        async with self._sessions() as session:
            await session.execute(
                delete(_OwnedKey).where(_OwnedKey.key_id == resource_id)
            )
            await session.commit()

    async def owned_fingerprints(self, *, user_id: str) -> dict[str, str]:
        async with self._sessions() as session:
            result = await session.execute(
                select(_OwnedKey.key_id, _OwnedKey.fingerprint).where(
                    _OwnedKey.user_id == user_id
                )
            )
            return {
                key_id: fingerprint
                for key_id, fingerprint in result.all()
                if fingerprint is not None
            }

    async def get_selected_model(self) -> str:
        async with self._sessions() as session:
            result = await session.execute(
                text(
                    "SELECT value FROM llm_provider_settings WHERE id='selected_model'"
                )
            )
            value = result.scalar_one_or_none()
        return str(value or "openrouter/free")

    async def set_selected_model(self, model_id: str, *, updated_by: str) -> str:
        async with self._sessions() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO llm_provider_settings (id, value, updated_by, updated_at)
                    VALUES ('selected_model', :value, :updated_by, NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        value = EXCLUDED.value,
                        updated_by = EXCLUDED.updated_by,
                        updated_at = EXCLUDED.updated_at
                    """
                ),
                {"value": model_id, "updated_by": updated_by},
            )
            await session.commit()
        return model_id


class _Base(DeclarativeBase):
    pass


class _OwnedKey(_Base):
    __tablename__ = "llm_provider_owned_keys"

    key_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(256), nullable=False)
    fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)


def _iso(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value) if value is not None else None


def _deployment_from_row(row: object) -> ProviderDeployment:
    data = row if isinstance(row, dict) else dict(row)  # type: ignore[arg-type]
    created_at = _iso(data["created_at"])
    if created_at is None:
        raise RuntimeError("provider deployment has no creation timestamp")
    return ProviderDeployment(
        id=str(data["id"]),
        user_id=str(data["user_id"]),
        label=str(data["label"]),
        suffix=str(data["suffix"]),
        fingerprint=str(data["fingerprint"]),
        model=str(data["model"]),
        created_at=created_at,
        status=str(data.get("status") or "healthy"),
        failure_count=max(0, int(data.get("failure_count") or 0)),
        cooldown_until=_iso(data.get("cooldown_until")),
        last_tested_at=_iso(data.get("last_tested_at")),
        last_used_at=_iso(data.get("last_used_at")),
        replacement_retire_at=_iso(data.get("replacement_retire_at")),
    )
