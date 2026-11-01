from __future__ import annotations

import asyncpg

SCHEMA_VERSION = 1
SCHEMA_VERSION_TABLE = "search_provider_schema_version"
TARGET_TABLES = (
    "organization_search_provider_keys",
    "organization_search_provider_preferences",
    "organization_search_provider_health",
)
LEGACY_TABLES = (
    "search_provider_keys",
    "search_provider_preferences",
    "search_provider_health",
)


async def initialize_schema(connection: asyncpg.Connection) -> None:
    """Create the clean-cut target schema and reject legacy provider tables."""

    await connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA_VERSION_TABLE} (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    legacy = [
        table
        for table in LEGACY_TABLES
        if await connection.fetchval("SELECT to_regclass($1)", f"public.{table}")
        is not None
    ]
    if legacy:
        joined = ", ".join(legacy)
        raise RuntimeError(
            "legacy Search provider tables are present; reset disposable data or "
            f"record an approved retained-data disposition before startup ({joined})"
        )

    current = await connection.fetchval(
        f"SELECT version FROM {SCHEMA_VERSION_TABLE} ORDER BY version DESC LIMIT 1"
    )
    if current is not None and int(current) != SCHEMA_VERSION:
        raise RuntimeError(
            "unsupported Search provider schema version "
            f"{current}; expected {SCHEMA_VERSION}"
        )

    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS organization_search_provider_keys (
            organization_id TEXT NOT NULL,
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
            PRIMARY KEY (organization_id, key_id),
            UNIQUE (organization_id, provider, fingerprint)
        )
        """
    )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS organization_search_provider_preferences (
            organization_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            enabled BOOLEAN NOT NULL,
            priority INTEGER NOT NULL CHECK (priority >= 0),
            PRIMARY KEY (organization_id, provider),
            UNIQUE (organization_id, priority)
        )
        """
    )
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS organization_search_provider_health (
            organization_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            failure_count INTEGER NOT NULL DEFAULT 0,
            cooldown_until TIMESTAMPTZ,
            PRIMARY KEY (organization_id, provider)
        )
        """
    )
    if current is None:
        await connection.execute(
            f"INSERT INTO {SCHEMA_VERSION_TABLE} (version) VALUES ($1)",
            SCHEMA_VERSION,
        )
