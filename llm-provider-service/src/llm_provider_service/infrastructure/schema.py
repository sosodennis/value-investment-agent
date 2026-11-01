from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

SCHEMA_VERSION = 1
SCHEMA_VERSION_TABLE = "llm_provider_schema_version"
TARGET_TABLES = (
    "llm_provider_organization_owned_keys",
    "llm_provider_organization_settings",
    "llm_provider_organization_deployments",
    "llm_provider_organization_key_import_batches",
    "llm_provider_organization_key_import_items",
)
LEGACY_TABLES = (
    "llm_provider_owned_keys",
    "llm_provider_settings",
    "llm_provider_deployments",
    "llm_provider_key_import_batches",
    "llm_provider_key_import_items",
)


async def initialize_schema(connection: AsyncConnection) -> None:
    """Create the clean-cut target schema and reject legacy provider tables."""

    await connection.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {SCHEMA_VERSION_TABLE} (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    legacy: list[str] = []
    for table in LEGACY_TABLES:
        result = await connection.execute(
            text("SELECT to_regclass(:qualified)"),
            {"qualified": f"public.{table}"},
        )
        if result.scalar_one_or_none() is not None:
            legacy.append(table)
    if legacy:
        joined = ", ".join(legacy)
        raise RuntimeError(
            "legacy LLM provider tables are present; reset disposable data or "
            f"record an approved retained-data disposition before startup ({joined})"
        )

    current = (
        await connection.execute(
            text(
                f"SELECT version FROM {SCHEMA_VERSION_TABLE} "
                "ORDER BY version DESC LIMIT 1"
            )
        )
    ).scalar_one_or_none()
    if current is not None and int(current) != SCHEMA_VERSION:
        raise RuntimeError(
            "unsupported LLM provider schema version "
            f"{current}; expected {SCHEMA_VERSION}"
        )

    statements = (
        """
        CREATE TABLE IF NOT EXISTS llm_provider_organization_owned_keys (
            key_id VARCHAR(255) PRIMARY KEY,
            organization_id VARCHAR(256) NOT NULL,
            fingerprint VARCHAR(128),
            UNIQUE (organization_id, fingerprint)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS llm_provider_organization_settings (
            organization_id VARCHAR(256) NOT NULL,
            id VARCHAR(80) NOT NULL,
            value VARCHAR(200) NOT NULL,
            updated_by VARCHAR(256) NOT NULL,
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            PRIMARY KEY (organization_id, id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS llm_provider_organization_deployments (
            id VARCHAR(255) PRIMARY KEY,
            organization_id VARCHAR(256) NOT NULL,
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
            UNIQUE (organization_id, fingerprint)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS llm_provider_organization_key_import_batches (
            id VARCHAR(36) PRIMARY KEY,
            organization_id VARCHAR(256) NOT NULL,
            idempotency_key VARCHAR(128) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'queued',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            UNIQUE (organization_id, idempotency_key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS llm_provider_organization_key_import_items (
            id VARCHAR(36) PRIMARY KEY,
            batch_id VARCHAR(36) NOT NULL REFERENCES
                llm_provider_organization_key_import_batches(id) ON DELETE CASCADE,
            organization_id VARCHAR(256) NOT NULL,
            source_line INTEGER NOT NULL,
            label VARCHAR(80) NOT NULL,
            encrypted_key TEXT,
            fingerprint VARCHAR(128) NOT NULL,
            suffix VARCHAR(16) NOT NULL,
            status VARCHAR(32) NOT NULL,
            error_code VARCHAR(64),
            attempts INTEGER NOT NULL DEFAULT 0,
            retryable BOOLEAN NOT NULL DEFAULT FALSE,
            next_retry_at TIMESTAMP WITH TIME ZONE,
            lease_owner VARCHAR(64),
            lease_until TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            UNIQUE (batch_id, source_line)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS
            ix_llm_provider_organization_key_import_items_pending
        ON llm_provider_organization_key_import_items
            (status, next_retry_at, lease_until, created_at)
        """,
        """
        CREATE INDEX IF NOT EXISTS
            ix_llm_provider_organization_key_import_items_owner_fingerprint
        ON llm_provider_organization_key_import_items (organization_id, fingerprint, status)
        """,
        """
        CREATE INDEX IF NOT EXISTS
            ix_llm_provider_organization_key_import_batches_owner_created
        ON llm_provider_organization_key_import_batches (organization_id, created_at DESC)
        """,
    )
    for statement in statements:
        await connection.execute(text(statement))
    if current is None:
        await connection.execute(
            text(f"INSERT INTO {SCHEMA_VERSION_TABLE} (version) VALUES (:version)"),
            {"version": SCHEMA_VERSION},
        )
