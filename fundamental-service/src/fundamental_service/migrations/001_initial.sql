CREATE SCHEMA IF NOT EXISTS fundamental;

CREATE TABLE IF NOT EXISTS fundamental.schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fundamental.model_releases (
    model_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    model_digest CHAR(64) NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (model_id, model_version)
);

CREATE TABLE IF NOT EXISTS fundamental.policy_releases (
    policy_id TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    policy_digest CHAR(64) NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (policy_id, policy_version)
);

CREATE TABLE IF NOT EXISTS fundamental.snapshot_manifests (
    snapshot_id TEXT PRIMARY KEY,
    manifest_digest CHAR(64) NOT NULL UNIQUE,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fundamental.canonical_facts (
    fact_id TEXT PRIMARY KEY,
    fact_digest CHAR(64) NOT NULL UNIQUE,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fundamental.mapping_decisions (
    mapping_id TEXT PRIMARY KEY,
    mapping_digest CHAR(64) NOT NULL UNIQUE,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fundamental.release_manifests (
    manifest_digest CHAR(64) PRIMARY KEY,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fundamental.content_objects (
    content_hash CHAR(64) NOT NULL,
    media_type TEXT NOT NULL,
    byte_length BIGINT NOT NULL CHECK (byte_length >= 0),
    volume TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (content_hash, media_type)
);

CREATE TABLE IF NOT EXISTS fundamental.artifact_references (
    artifact_id TEXT PRIMARY KEY,
    content_hash CHAR(64) NOT NULL,
    media_type TEXT NOT NULL,
    dependency_hashes JSONB NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('valid', 'stale', 'invalidated')),
    retention TEXT NOT NULL CHECK (retention IN ('evidence', 'operational_cache')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO fundamental.schema_migrations(version)
VALUES ('fundamental-metadata-v1')
ON CONFLICT (version) DO NOTHING;
