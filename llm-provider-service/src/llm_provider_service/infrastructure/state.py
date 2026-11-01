from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String, delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from src.llm_provider_service.domain.errors import ProviderSettingsError
from src.llm_provider_service.domain.key_imports import (
    ClaimedKeyImportItem,
    ImportBatchStatus,
    ImportItemStatus,
    KeyImportInput,
    KeyImportItemSnapshot,
    KeyImportSnapshot,
)
from src.llm_provider_service.domain.key_metadata import key_fingerprint, key_suffix

from .schema import initialize_schema


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
    organization_id: str
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
            # target-schema creation so PostgreSQL does not race while creating
            # the same relation type.
            await connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                {"lock_key": "llm-provider-schema-initialize"},
            )
            await initialize_schema(connection)

    async def close(self) -> None:
        await self._engine.dispose()

    async def rotate_encryption_key(self, *, old_key: str, new_key: str) -> int:
        """Re-encrypt organization provider ciphertext in one transaction."""

        try:
            old_cipher = Fernet(old_key.encode("ascii"))
            new_cipher = Fernet(new_key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise ValueError("encryption keys must be Fernet keys") from exc
        updated = 0
        async with self._engine.begin() as connection:
            for table in (
                "llm_provider_organization_deployments",
                "llm_provider_organization_key_import_items",
            ):
                rows = (
                    await connection.execute(
                        text(
                            f"SELECT id,encrypted_key FROM {table} "
                            "WHERE encrypted_key IS NOT NULL FOR UPDATE"
                        )
                    )
                ).mappings()
                for row in rows:
                    try:
                        plaintext = old_cipher.decrypt(
                            str(row["encrypted_key"]).encode("ascii")
                        )
                    except Exception as exc:
                        raise RuntimeError(
                            "stored LLM provider credential cannot be re-encrypted"
                        ) from exc
                    await connection.execute(
                        text(
                            f"UPDATE {table} SET encrypted_key=:encrypted_key "
                            "WHERE id=:id"
                        ),
                        {
                            "id": row["id"],
                            "encrypted_key": new_cipher.encrypt(plaintext).decode(
                                "ascii"
                            ),
                        },
                    )
                    updated += 1
        self._cipher = new_cipher
        return updated

    def _require_cipher(self) -> Fernet:
        if self._cipher is None:
            raise RuntimeError("LLM_PROVIDER_ENCRYPTION_KEY is required")
        return self._cipher

    async def list_deployments(
        self, *, organization_id: str
    ) -> list[ProviderDeployment]:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT id,organization_id,label,suffix,fingerprint,model,created_at,
                               status,failure_count,cooldown_until,last_tested_at,
                               last_used_at,replacement_retire_at
                        FROM llm_provider_organization_deployments
                        WHERE organization_id=:organization_id
                        ORDER BY created_at,id
                        """,
                        {"organization_id": organization_id},
                    )
                )
            ).mappings()
            return [_deployment_from_row(row) for row in rows]

    async def list_all_deployments(self) -> list[ProviderDeployment]:
        """List deployment metadata for the process-owned cleanup worker."""

        async with self._sessions() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT id,organization_id,label,suffix,fingerprint,model,created_at,
                               status,failure_count,cooldown_until,last_tested_at,
                               last_used_at,replacement_retire_at
                        FROM llm_provider_organization_deployments
                        ORDER BY created_at,id
                        """
                    )
                )
            ).mappings()
            return [_deployment_from_row(row) for row in rows]

    async def get_deployment(
        self, *, organization_id: str, deployment_id: str
    ) -> ProviderDeployment | None:
        async with self._sessions() as session:
            row = (
                (
                    await session.execute(
                        text(
                            """
                        SELECT id,organization_id,label,suffix,fingerprint,model,created_at,
                               status,failure_count,cooldown_until,last_tested_at,
                               last_used_at,replacement_retire_at
                        FROM llm_provider_organization_deployments
                        WHERE id=:id AND organization_id=:organization_id
                        """
                        ),
                        {"id": deployment_id, "organization_id": organization_id},
                    )
                )
                .mappings()
                .first()
            )
            return _deployment_from_row(row) if row is not None else None

    async def find_deployment_by_fingerprint(
        self, *, organization_id: str, fingerprint: str
    ) -> ProviderDeployment | None:
        async with self._sessions() as session:
            row = (
                (
                    await session.execute(
                        text(
                            """
                        SELECT id,organization_id,label,suffix,fingerprint,model,created_at,
                               status,failure_count,cooldown_until,last_tested_at,
                               last_used_at,replacement_retire_at
                        FROM llm_provider_organization_deployments
                        WHERE organization_id=:organization_id AND fingerprint=:fingerprint
                        """
                        ),
                        {
                            "organization_id": organization_id,
                            "fingerprint": fingerprint,
                        },
                    )
                )
                .mappings()
                .first()
            )
            return _deployment_from_row(row) if row is not None else None

    async def deployment_key(self, *, organization_id: str, deployment_id: str) -> str:
        cipher = self._require_cipher()
        async with self._sessions() as session:
            encrypted = (
                await session.execute(
                    text(
                        "SELECT encrypted_key FROM llm_provider_organization_deployments "
                        "WHERE id=:id AND organization_id=:organization_id"
                    ),
                    {"id": deployment_id, "organization_id": organization_id},
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
        organization_id: str,
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
                    INSERT INTO llm_provider_organization_deployments
                    (id,organization_id,encrypted_key,label,suffix,fingerprint,model,created_at,
                     status,last_tested_at)
                    VALUES (:id,:organization_id,:encrypted_key,:label,:suffix,:fingerprint,
                            :model,:created_at,'healthy',:created_at)
                    """
                ),
                {
                    "id": identifier,
                    "organization_id": organization_id,
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
        result = await self.get_deployment(
            organization_id=organization_id, deployment_id=identifier
        )
        if result is None:
            raise RuntimeError("provider deployment was not persisted")
        return result

    async def update_deployment(
        self, *, organization_id: str, deployment_id: str, **values: object
    ) -> None:
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
                text(
                    f"UPDATE llm_provider_organization_deployments SET {assignments} "
                    "WHERE id=:id AND organization_id=:organization_id"
                ),
                {**updates, "id": deployment_id, "organization_id": organization_id},
            )
            await session.commit()

    async def delete_deployment(
        self, *, organization_id: str, deployment_id: str
    ) -> None:
        async with self._sessions() as session:
            await session.execute(
                text(
                    "DELETE FROM llm_provider_organization_deployments "
                    "WHERE id=:id AND organization_id=:organization_id"
                ),
                {"id": deployment_id, "organization_id": organization_id},
            )
            await session.execute(
                delete(_OwnedKey)
                .where(_OwnedKey.key_id == deployment_id)
                .where(_OwnedKey.organization_id == organization_id)
            )
            await session.commit()

    async def update_all_deployment_models(
        self, *, organization_id: str, model: str
    ) -> None:
        async with self._sessions() as session:
            await session.execute(
                text(
                    "UPDATE llm_provider_organization_deployments SET model=:model "
                    "WHERE organization_id=:organization_id"
                ),
                {"model": model, "organization_id": organization_id},
            )
            await session.commit()

    @asynccontextmanager
    async def replacement_lock(
        self, *, organization_id: str, key_id: str
    ) -> AsyncIterator[None]:
        lock_key = f"llm-provider-replacement:{organization_id}:{key_id}"
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

    @asynccontextmanager
    async def fingerprint_lock(
        self, *, organization_id: str, fingerprint: str
    ) -> AsyncIterator[None]:
        lock_key = f"llm-provider-key-fingerprint:{organization_id}:{fingerprint}"
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
        organization_id: str,
        resource_type: str,
        resource_id: str,
        fingerprint: str | None = None,
    ) -> bool:
        _ = resource_type
        async with self._sessions() as session:
            session.add(
                _OwnedKey(
                    key_id=resource_id,
                    organization_id=organization_id,
                    fingerprint=fingerprint,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                row = await session.get(_OwnedKey, resource_id)
                return row is not None and row.organization_id == organization_id
        return True

    async def owns(
        self, *, organization_id: str, resource_type: str, resource_id: str
    ) -> bool:
        _ = resource_type
        async with self._sessions() as session:
            row = await session.get(_OwnedKey, resource_id)
            return row is not None and row.organization_id == organization_id

    async def owned_ids(self, *, organization_id: str, resource_type: str) -> set[str]:
        _ = resource_type
        async with self._sessions() as session:
            result = await session.execute(
                select(_OwnedKey.key_id).where(
                    _OwnedKey.organization_id == organization_id
                )
            )
            return set(result.scalars().all())

    async def find_by_fingerprint(
        self, *, organization_id: str, fingerprint: str
    ) -> str | None:
        async with self._sessions() as session:
            result = await session.execute(
                select(_OwnedKey.key_id)
                .where(_OwnedKey.organization_id == organization_id)
                .where(_OwnedKey.fingerprint == fingerprint)
            )
            return result.scalar_one_or_none()

    async def release(
        self, *, organization_id: str, resource_type: str, resource_id: str
    ) -> None:
        _ = resource_type
        async with self._sessions() as session:
            await session.execute(
                delete(_OwnedKey)
                .where(_OwnedKey.key_id == resource_id)
                .where(_OwnedKey.organization_id == organization_id)
            )
            await session.commit()

    async def owned_fingerprints(self, *, organization_id: str) -> dict[str, str]:
        async with self._sessions() as session:
            result = await session.execute(
                select(_OwnedKey.key_id, _OwnedKey.fingerprint).where(
                    _OwnedKey.organization_id == organization_id
                )
            )
            return {
                key_id: fingerprint
                for key_id, fingerprint in result.all()
                if fingerprint is not None
            }

    async def get_selected_model(self, *, organization_id: str) -> str:
        async with self._sessions() as session:
            result = await session.execute(
                text(
                    "SELECT value FROM llm_provider_organization_settings "
                    "WHERE organization_id=:organization_id AND id='selected_model'"
                ),
                {"organization_id": organization_id},
            )
            value = result.scalar_one_or_none()
        return str(value or "openrouter/free")

    async def set_selected_model(
        self, model_id: str, *, organization_id: str, updated_by: str
    ) -> str:
        async with self._sessions() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO llm_provider_organization_settings
                        (organization_id, id, value, updated_by, updated_at)
                    VALUES (:organization_id, 'selected_model', :value, :updated_by, NOW())
                    ON CONFLICT (organization_id, id) DO UPDATE SET
                        value = EXCLUDED.value,
                        updated_by = EXCLUDED.updated_by,
                        updated_at = EXCLUDED.updated_at
                    """
                ),
                {
                    "organization_id": organization_id,
                    "value": model_id,
                    "updated_by": updated_by,
                },
            )
            await session.commit()
        return model_id

    async def create_key_import(
        self,
        *,
        organization_id: str,
        idempotency_key: str,
        items: list[KeyImportInput],
    ) -> KeyImportSnapshot:
        cipher = self._require_cipher()
        batch_id = str(uuid4())
        now = datetime.now(UTC)
        stage_expires_at = now + timedelta(days=7)
        batch_expires_at = now + timedelta(days=30)
        async with self._sessions() as session:
            async with session.begin():
                await session.execute(
                    text(
                        "SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"
                    ),
                    {"lock_key": f"llm-provider-import-owner:{organization_id}"},
                )
                existing_id = await session.execute(
                    text(
                        """
                        SELECT id FROM llm_provider_organization_key_import_batches
                        WHERE organization_id=:organization_id AND idempotency_key=:idempotency_key
                        """
                    ),
                    {
                        "organization_id": organization_id,
                        "idempotency_key": idempotency_key,
                    },
                )
                existing_id_value = existing_id.scalar_one_or_none()
                if isinstance(existing_id_value, str):
                    stored_items = await session.execute(
                        text(
                            """
                            SELECT source_line,label,fingerprint
                            FROM llm_provider_organization_key_import_items
                            WHERE batch_id=:batch_id
                            ORDER BY source_line
                            """
                        ),
                        {"batch_id": existing_id_value},
                    )
                    stored_signature = [
                        (int(line), str(label), str(fingerprint))
                        for line, label, fingerprint in stored_items.all()
                    ]
                    requested_signature = [
                        (
                            item.source_line,
                            _safe_key_label(item.label, item.api_key),
                            key_fingerprint(item.api_key),
                        )
                        for item in items
                    ]
                    if stored_signature != requested_signature:
                        raise ProviderSettingsError("idempotency_key_reused")
                    batch_id = existing_id_value
                else:
                    deployed = await session.execute(
                        text(
                            """
                            SELECT fingerprint FROM llm_provider_organization_deployments
                            WHERE organization_id=:organization_id
                            """
                        ),
                        {"organization_id": organization_id},
                    )
                    owned_fingerprints = set(deployed.scalars().all())
                    pending = await session.execute(
                        text(
                            """
                            SELECT fingerprint FROM llm_provider_organization_key_import_items
                            WHERE organization_id=:organization_id
                              AND status IN ('queued','validating','retry_wait')
                              AND expires_at > NOW()
                            """
                        ),
                        {"organization_id": organization_id},
                    )
                    pending_fingerprints = set(pending.scalars().all())
                    await session.execute(
                        text(
                            """
                            INSERT INTO llm_provider_organization_key_import_batches
                                (id,organization_id,idempotency_key,status,created_at,updated_at,
                                 expires_at)
                            VALUES (:id,:organization_id,:idempotency_key,'queued',:now,:now,
                                    :expires_at)
                            """
                        ),
                        {
                            "id": batch_id,
                            "organization_id": organization_id,
                            "idempotency_key": idempotency_key,
                            "now": now,
                            "expires_at": batch_expires_at,
                        },
                    )
                    seen: set[str] = set()
                    for item in items:
                        fingerprint = key_fingerprint(item.api_key)
                        suffix = key_suffix(item.api_key)
                        safe_label = _safe_key_label(item.label, item.api_key)
                        error_code: str | None = None
                        if fingerprint in seen:
                            status = "duplicate"
                            error_code = "duplicate_in_batch"
                        elif fingerprint in owned_fingerprints:
                            status = "duplicate"
                            error_code = "already_owned"
                        elif fingerprint in pending_fingerprints:
                            status = "duplicate"
                            error_code = "already_importing"
                        else:
                            status = "queued"
                        seen.add(fingerprint)
                        encrypted_key = (
                            cipher.encrypt(item.api_key.encode("utf-8")).decode("ascii")
                            if status == "queued"
                            else None
                        )
                        await session.execute(
                            text(
                                """
                                INSERT INTO llm_provider_organization_key_import_items
                                    (id,batch_id,organization_id,source_line,label,encrypted_key,
                                     fingerprint,suffix,status,error_code,attempts,
                                     retryable,created_at,updated_at,expires_at)
                                VALUES (:id,:batch_id,:organization_id,:source_line,:label,
                                        :encrypted_key,:fingerprint,:suffix,:status,
                                        :error_code,0,FALSE,:now,:now,:expires_at)
                                """
                            ),
                            {
                                "id": str(uuid4()),
                                "batch_id": batch_id,
                                "organization_id": organization_id,
                                "source_line": item.source_line,
                                "label": safe_label,
                                "encrypted_key": encrypted_key,
                                "fingerprint": fingerprint,
                                "suffix": suffix,
                                "status": status,
                                "error_code": error_code,
                                "now": now,
                                "expires_at": stage_expires_at,
                            },
                        )
                    await self._refresh_import_batch(session, batch_id)
        snapshot = await self.get_key_import(
            organization_id=organization_id, batch_id=batch_id
        )
        if snapshot is None:
            raise RuntimeError("provider key import was not persisted")
        return snapshot

    async def list_key_imports(
        self, *, organization_id: str, limit: int = 10
    ) -> list[KeyImportSnapshot]:
        async with self._sessions() as session:
            rows = await session.execute(
                text(
                    """
                    SELECT id FROM llm_provider_organization_key_import_batches
                    WHERE organization_id=:organization_id AND expires_at > NOW()
                    ORDER BY created_at DESC,id DESC LIMIT :limit
                    """
                ),
                {"organization_id": organization_id, "limit": min(max(limit, 1), 50)},
            )
            batch_ids = list(rows.scalars().all())
        snapshots: list[KeyImportSnapshot] = []
        for batch_id in batch_ids:
            snapshot = await self.get_key_import(
                organization_id=organization_id, batch_id=str(batch_id)
            )
            if snapshot is not None:
                snapshots.append(snapshot)
        return snapshots

    async def get_key_import(
        self, *, organization_id: str, batch_id: str
    ) -> KeyImportSnapshot | None:
        async with self._sessions() as session:
            batch = (
                (
                    await session.execute(
                        text(
                            """
                        SELECT id,status,created_at,updated_at
                        FROM llm_provider_organization_key_import_batches
                        WHERE id=:batch_id AND organization_id=:organization_id
                          AND expires_at > NOW()
                        """
                        ),
                        {"batch_id": batch_id, "organization_id": organization_id},
                    )
                )
                .mappings()
                .first()
            )
            if batch is None:
                return None
            rows = (
                (
                    await session.execute(
                        text(
                            """
                        SELECT source_line,label,suffix,status,error_code,attempts,
                               retryable
                        FROM llm_provider_organization_key_import_items
                        WHERE batch_id=:batch_id AND organization_id=:organization_id
                        ORDER BY source_line,id
                        """
                        ),
                        {"batch_id": batch_id, "organization_id": organization_id},
                    )
                )
                .mappings()
                .all()
            )
        items = tuple(
            KeyImportItemSnapshot(
                source_line=int(row["source_line"]),
                label=str(row["label"]),
                suffix=(str(row["suffix"]) if row["suffix"] is not None else None),
                status=_import_item_status(str(row["status"])),
                error_code=(
                    str(row["error_code"]) if row["error_code"] is not None else None
                ),
                attempts=max(0, int(row["attempts"])),
                retryable=bool(row["retryable"]),
            )
            for row in rows
        )
        imported_count = sum(item.status == "imported" for item in items)
        duplicate_count = sum(item.status == "duplicate" for item in items)
        invalid_count = sum(
            item.status in {"invalid", "unavailable", "expired"} for item in items
        )
        retryable_count = sum(item.retryable for item in items)
        processed_count = sum(
            item.status not in {"queued", "validating", "retry_wait"} for item in items
        )
        return KeyImportSnapshot(
            id=str(batch["id"]),
            status=_import_batch_status(items),
            total_count=len(items),
            processed_count=processed_count,
            imported_count=imported_count,
            duplicate_count=duplicate_count,
            invalid_count=invalid_count,
            retryable_count=retryable_count,
            created_at=_required_iso(batch["created_at"]),
            updated_at=_required_iso(batch["updated_at"]),
            items=items,
        )

    async def claim_key_import_items(
        self, *, worker_id: str, limit: int, lease_seconds: int = 45
    ) -> list[ClaimedKeyImportItem]:
        cipher = self._require_cipher()
        now = datetime.now(UTC)
        async with self._sessions() as session:
            async with session.begin():
                expired = await session.execute(
                    text(
                        """
                        UPDATE llm_provider_organization_key_import_items
                        SET status='unavailable',error_code='worker_attempts_exhausted',
                            retryable=TRUE,lease_owner=NULL,lease_until=NULL,
                            updated_at=:now
                        WHERE status='validating' AND lease_until <= :now
                          AND attempts >= 3 AND encrypted_key IS NOT NULL
                        RETURNING batch_id
                        """
                    ),
                    {"now": now},
                )
                changed_batches = {str(value) for value in expired.scalars().all()}
                rows = (
                    (
                        await session.execute(
                            text(
                                """
                            WITH selected AS (
                                SELECT id
                                FROM llm_provider_organization_key_import_items
                                WHERE (
                                    (status IN ('queued','retry_wait')
                                     AND (next_retry_at IS NULL OR next_retry_at <= :now))
                                    OR (status='validating' AND lease_until <= :now)
                                )
                                  AND attempts < 3
                                  AND encrypted_key IS NOT NULL
                                  AND expires_at > :now
                                ORDER BY created_at,source_line,id
                                LIMIT :limit FOR UPDATE SKIP LOCKED
                            )
                            UPDATE llm_provider_organization_key_import_items AS item
                            SET status='validating',attempts=item.attempts+1,
                                next_retry_at=NULL,lease_owner=:worker_id,
                                lease_until=:lease_until,updated_at=:now
                            FROM selected
                            WHERE item.id=selected.id
                            RETURNING item.id,item.batch_id,item.organization_id,
                                item.source_line,item.label,item.fingerprint,item.suffix,
                                item.encrypted_key,item.attempts
                            """
                            ),
                            {
                                "now": now,
                                "limit": min(max(limit, 1), 50),
                                "worker_id": worker_id,
                                "lease_until": now + timedelta(seconds=lease_seconds),
                            },
                        )
                    )
                    .mappings()
                    .all()
                )
                claimed: list[ClaimedKeyImportItem] = []
                for row in rows:
                    try:
                        key = cipher.decrypt(
                            str(row["encrypted_key"]).encode("ascii")
                        ).decode("utf-8")
                    except (InvalidToken, UnicodeDecodeError):
                        await session.execute(
                            text(
                                """
                                UPDATE llm_provider_organization_key_import_items
                                SET status='unavailable',error_code='staging_unavailable',
                                    retryable=FALSE,encrypted_key=NULL,
                                    lease_owner=NULL,lease_until=NULL,updated_at=:now
                                WHERE id=:id AND lease_owner=:worker_id
                                """
                            ),
                            {
                                "id": row["id"],
                                "worker_id": worker_id,
                                "now": now,
                            },
                        )
                        changed_batches.add(str(row["batch_id"]))
                        continue
                    claimed.append(
                        ClaimedKeyImportItem(
                            id=str(row["id"]),
                            batch_id=str(row["batch_id"]),
                            organization_id=str(row["organization_id"]),
                            source_line=int(row["source_line"]),
                            label=str(row["label"]),
                            fingerprint=str(row["fingerprint"]),
                            suffix=str(row["suffix"]),
                            api_key=key,
                            attempts=int(row["attempts"]),
                            worker_id=worker_id,
                        )
                    )
                for batch_id in {item.batch_id for item in claimed}:
                    changed_batches.add(batch_id)
                for batch_id in changed_batches:
                    await self._refresh_import_batch(session, batch_id)
        return claimed

    async def find_import_deployment(
        self, *, organization_id: str, fingerprint: str
    ) -> str | None:
        async with self._sessions() as session:
            result = await session.execute(
                text(
                    """
                    SELECT id FROM llm_provider_organization_deployments
                    WHERE organization_id=:organization_id AND fingerprint=:fingerprint
                    """
                ),
                {"organization_id": organization_id, "fingerprint": fingerprint},
            )
            value = result.scalar_one_or_none()
        return str(value) if value is not None else None

    async def finish_import_duplicate(self, *, item: ClaimedKeyImportItem) -> None:
        now = datetime.now(UTC)
        async with self._sessions() as session:
            async with session.begin():
                deployment_id = (
                    await session.execute(
                        text(
                            """
                            SELECT id FROM llm_provider_organization_deployments
                            WHERE organization_id=:organization_id AND fingerprint=:fingerprint
                            """
                        ),
                        {
                            "organization_id": item.organization_id,
                            "fingerprint": item.fingerprint,
                        },
                    )
                ).scalar_one_or_none()
                if deployment_id is not None:
                    await session.execute(
                        text(
                            """
                            INSERT INTO llm_provider_organization_owned_keys
                                (key_id,organization_id,fingerprint)
                            VALUES (:key_id,:organization_id,:fingerprint)
                            ON CONFLICT DO NOTHING
                            """
                        ),
                        {
                            "key_id": str(deployment_id),
                            "organization_id": item.organization_id,
                            "fingerprint": item.fingerprint,
                        },
                    )
                await session.execute(
                    text(
                        """
                        UPDATE llm_provider_organization_key_import_items
                        SET status='duplicate',error_code='already_owned',
                            retryable=FALSE,encrypted_key=NULL,lease_owner=NULL,
                            lease_until=NULL,updated_at=:now
                        WHERE id=:id AND status='validating' AND lease_owner=:worker_id
                        """
                    ),
                    {"id": item.id, "worker_id": item.worker_id, "now": now},
                )
                await self._refresh_import_batch(session, item.batch_id)

    async def finish_import_success(
        self, *, item: ClaimedKeyImportItem, model: str
    ) -> bool:
        cipher = self._require_cipher()
        now = datetime.now(UTC)
        deployment_id = str(uuid4())
        encrypted_key = cipher.encrypt(item.api_key.encode("utf-8")).decode("ascii")
        async with self._sessions() as session:
            async with session.begin():
                current = (
                    await session.execute(
                        text(
                            """
                            SELECT id FROM llm_provider_organization_key_import_items
                            WHERE id=:id AND status='validating'
                              AND lease_owner=:worker_id FOR UPDATE
                            """
                        ),
                        {"id": item.id, "worker_id": item.worker_id},
                    )
                ).scalar_one_or_none()
                if current is None:
                    return False
                existing_owned = (
                    await session.execute(
                        text(
                            """
                            SELECT key_id FROM llm_provider_organization_owned_keys
                            WHERE organization_id=:organization_id AND fingerprint=:fingerprint
                            """
                        ),
                        {
                            "organization_id": item.organization_id,
                            "fingerprint": item.fingerprint,
                        },
                    )
                ).scalar_one_or_none()
                if existing_owned is not None:
                    await session.execute(
                        text(
                            """
                            UPDATE llm_provider_organization_key_import_items
                            SET status='duplicate',error_code='already_owned',
                                retryable=FALSE,encrypted_key=NULL,lease_owner=NULL,
                                lease_until=NULL,updated_at=:now
                            WHERE id=:id
                            """
                        ),
                        {"id": item.id, "now": now},
                    )
                    await self._refresh_import_batch(session, item.batch_id)
                    return False
                existing_deployment = (
                    await session.execute(
                        text(
                            """
                            SELECT id FROM llm_provider_organization_deployments
                            WHERE organization_id=:organization_id AND fingerprint=:fingerprint
                            """
                        ),
                        {
                            "organization_id": item.organization_id,
                            "fingerprint": item.fingerprint,
                        },
                    )
                ).scalar_one_or_none()
                if existing_deployment is None:
                    await session.execute(
                        text(
                            """
                            INSERT INTO llm_provider_organization_deployments
                                (id,organization_id,encrypted_key,label,suffix,fingerprint,model,
                                 created_at,status,last_tested_at)
                            VALUES (:id,:organization_id,:encrypted_key,:label,:suffix,
                                    :fingerprint,:model,:now,'healthy',:now)
                            """
                        ),
                        {
                            "id": deployment_id,
                            "organization_id": item.organization_id,
                            "encrypted_key": encrypted_key,
                            "label": item.label,
                            "suffix": item.suffix,
                            "fingerprint": item.fingerprint,
                            "model": model,
                            "now": now,
                        },
                    )
                else:
                    deployment_id = str(existing_deployment)
                await session.execute(
                    text(
                        """
                        INSERT INTO llm_provider_organization_owned_keys (key_id,organization_id,fingerprint)
                        VALUES (:key_id,:organization_id,:fingerprint)
                        ON CONFLICT DO NOTHING
                        """
                    ),
                    {
                        "key_id": deployment_id,
                        "organization_id": item.organization_id,
                        "fingerprint": item.fingerprint,
                    },
                )
                await session.execute(
                    text(
                        """
                        UPDATE llm_provider_organization_key_import_items
                        SET status='imported',error_code=NULL,retryable=FALSE,
                            encrypted_key=NULL,lease_owner=NULL,lease_until=NULL,
                            updated_at=:now
                        WHERE id=:id
                        """
                    ),
                    {"id": item.id, "now": now},
                )
                await self._refresh_import_batch(session, item.batch_id)
        return True

    async def finish_import_failure(
        self,
        *,
        item: ClaimedKeyImportItem,
        error_code: str,
        retryable: bool,
        delay_seconds: float,
    ) -> None:
        now = datetime.now(UTC)
        retry_pending = retryable and item.attempts < 3
        status = (
            "retry_wait"
            if retry_pending
            else ("unavailable" if retryable else "invalid")
        )
        async with self._sessions() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        UPDATE llm_provider_organization_key_import_items
                        SET status=:status,error_code=:error_code,
                            retryable=:retryable,
                            encrypted_key=CASE WHEN :retryable THEN encrypted_key ELSE NULL END,
                            next_retry_at=CASE WHEN :retry_pending
                                THEN :next_retry_at
                                ELSE CAST(NULL AS TIMESTAMP WITH TIME ZONE) END,
                            lease_owner=NULL,lease_until=NULL,updated_at=:now
                        WHERE id=:id AND status='validating' AND lease_owner=:worker_id
                        """
                    ),
                    {
                        "id": item.id,
                        "worker_id": item.worker_id,
                        "status": status,
                        "error_code": error_code,
                        "retryable": retryable,
                        "retry_pending": retry_pending,
                        "next_retry_at": now + timedelta(seconds=max(delay_seconds, 0)),
                        "now": now,
                    },
                )
                await self._refresh_import_batch(session, item.batch_id)

    async def retry_key_import(
        self, *, organization_id: str, batch_id: str
    ) -> KeyImportSnapshot | None:
        now = datetime.now(UTC)
        async with self._sessions() as session:
            async with session.begin():
                exists = (
                    await session.execute(
                        text(
                            """
                            SELECT id FROM llm_provider_organization_key_import_batches
                            WHERE id=:batch_id AND organization_id=:organization_id
                              AND expires_at > :now FOR UPDATE
                            """
                        ),
                        {
                            "batch_id": batch_id,
                            "organization_id": organization_id,
                            "now": now,
                        },
                    )
                ).scalar_one_or_none()
                if exists is None:
                    return None
                await session.execute(
                    text(
                        """
                        UPDATE llm_provider_organization_key_import_items
                        SET status='queued',attempts=0,error_code=NULL,
                            retryable=FALSE,next_retry_at=NULL,updated_at=:now
                        WHERE batch_id=:batch_id AND organization_id=:organization_id
                          AND status='unavailable' AND retryable=TRUE
                          AND encrypted_key IS NOT NULL AND expires_at > :now
                        """
                    ),
                    {
                        "batch_id": batch_id,
                        "organization_id": organization_id,
                        "now": now,
                    },
                )
                await self._refresh_import_batch(session, batch_id)
        return await self.get_key_import(
            organization_id=organization_id, batch_id=batch_id
        )

    async def cleanup_key_imports(self) -> int:
        now = datetime.now(UTC)
        async with self._sessions() as session:
            async with session.begin():
                expired = await session.execute(
                    text(
                        """
                        UPDATE llm_provider_organization_key_import_items
                        SET status='expired',error_code='retry_expired',retryable=FALSE,
                            encrypted_key=NULL,next_retry_at=NULL,lease_owner=NULL,
                            lease_until=NULL,updated_at=:now
                        WHERE encrypted_key IS NOT NULL AND expires_at <= :now
                        RETURNING batch_id
                        """
                    ),
                    {"now": now},
                )
                affected_batches = set(expired.scalars().all())
                for batch_id in affected_batches:
                    await self._refresh_import_batch(session, str(batch_id))
                deleted = await session.execute(
                    text(
                        """
                        DELETE FROM llm_provider_organization_key_import_batches
                        WHERE expires_at <= :now
                        """
                    ),
                    {"now": now},
                )
        return len(affected_batches) + max(deleted.rowcount or 0, 0)

    @staticmethod
    async def _refresh_import_batch(session: object, batch_id: str) -> None:
        # Item completions run concurrently on different worker sessions. Lock
        # the batch before deriving its aggregate status so the last committer
        # observes every prior item update instead of persisting a stale
        # ``processing`` value.
        await session.execute(
            text(
                """
                SELECT id FROM llm_provider_organization_key_import_batches
                WHERE id=:batch_id
                FOR UPDATE
                """
            ),
            {"batch_id": batch_id},
        )
        await session.execute(
            text(
                """
                UPDATE llm_provider_organization_key_import_batches AS batch
                SET status=CASE
                    WHEN EXISTS (
                        SELECT 1 FROM llm_provider_organization_key_import_items AS item
                        WHERE item.batch_id=batch.id AND item.status='validating'
                    ) THEN 'processing'
                    WHEN EXISTS (
                        SELECT 1 FROM llm_provider_organization_key_import_items AS item
                        WHERE item.batch_id=batch.id AND item.status='queued'
                    ) THEN 'queued'
                    WHEN EXISTS (
                        SELECT 1 FROM llm_provider_organization_key_import_items AS item
                        WHERE item.batch_id=batch.id AND item.status='retry_wait'
                    ) THEN 'processing'
                    WHEN EXISTS (
                        SELECT 1 FROM llm_provider_organization_key_import_items AS item
                        WHERE item.batch_id=batch.id
                          AND item.status IN ('invalid','unavailable','expired')
                    ) THEN 'completed_with_errors'
                    ELSE 'completed'
                END,
                updated_at=NOW()
                WHERE batch.id=:batch_id
                """
            ),
            {"batch_id": batch_id},
        )


class _Base(DeclarativeBase):
    pass


def _safe_key_label(label: str, api_key: str) -> str:
    safe = label.strip() or "OpenRouter key"
    if api_key in safe:
        safe = safe.replace(api_key, "[redacted]")
    return safe[:80]


def _import_item_status(value: str) -> ImportItemStatus:
    allowed: tuple[ImportItemStatus, ...] = (
        "queued",
        "validating",
        "retry_wait",
        "imported",
        "duplicate",
        "invalid",
        "unavailable",
        "expired",
    )
    if value not in allowed:
        raise RuntimeError("provider key import item status is invalid")
    return value


def _import_batch_status(
    items: tuple[KeyImportItemSnapshot, ...],
) -> ImportBatchStatus:
    statuses = {item.status for item in items}
    if "validating" in statuses or "retry_wait" in statuses:
        return "processing"
    if "queued" in statuses:
        return "queued"
    if statuses & {"invalid", "unavailable", "expired"}:
        return "completed_with_errors"
    return "completed"


def _required_iso(value: object) -> str:
    result = _iso(value)
    if result is None:
        raise RuntimeError("provider key import has no timestamp")
    return result


class _OwnedKey(_Base):
    __tablename__ = "llm_provider_organization_owned_keys"

    key_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(256), nullable=False)
    fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)


def _iso(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value) if value is not None else None


def _deployment_from_row(row: Mapping[str, object]) -> ProviderDeployment:
    created_at = _iso(row["created_at"])
    if created_at is None:
        raise RuntimeError("provider deployment has no creation timestamp")
    return ProviderDeployment(
        id=str(row["id"]),
        organization_id=str(row["organization_id"]),
        label=str(row["label"]),
        suffix=str(row["suffix"]),
        fingerprint=str(row["fingerprint"]),
        model=str(row["model"]),
        created_at=created_at,
        status=str(row.get("status") or "healthy"),
        failure_count=max(0, int(row.get("failure_count") or 0)),
        cooldown_until=_iso(row.get("cooldown_until")),
        last_tested_at=_iso(row.get("last_tested_at")),
        last_used_at=_iso(row.get("last_used_at")),
        replacement_retire_at=_iso(row.get("replacement_retire_at")),
    )
