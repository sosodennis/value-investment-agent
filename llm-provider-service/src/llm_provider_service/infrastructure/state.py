from __future__ import annotations

import os

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


class ProviderState:
    def __init__(self) -> None:
        self._engine = create_async_engine(_database_url(), pool_pre_ping=True)
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)

    async def initialize(self) -> None:
        async with self._engine.begin() as connection:
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
