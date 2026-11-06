CREATE TABLE IF NOT EXISTS fundamental.snapshot_facts (
    snapshot_id TEXT NOT NULL REFERENCES fundamental.snapshot_manifests(snapshot_id),
    fact_id TEXT NOT NULL REFERENCES fundamental.canonical_facts(fact_id),
    PRIMARY KEY (snapshot_id, fact_id)
);

CREATE TABLE IF NOT EXISTS fundamental.sec_ingestion_acquisitions (
    acquisition_key CHAR(64) PRIMARY KEY,
    acquisition_payload JSONB NOT NULL,
    snapshot_id TEXT NOT NULL REFERENCES fundamental.snapshot_manifests(snapshot_id),
    fact_ids JSONB NOT NULL,
    result_payload JSONB NOT NULL,
    caller_principal TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS sec_ingestion_acquisitions_snapshot_idx
    ON fundamental.sec_ingestion_acquisitions(snapshot_id);

CREATE TABLE IF NOT EXISTS fundamental.source_acquisition_audits (
    audit_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    acquisition_key CHAR(64) NOT NULL,
    caller_principal TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    source_hashes JSONB NOT NULL,
    outcome TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fundamental.sec_provider_rate_limits (
    rate_key TEXT PRIMARY KEY,
    next_request_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS source_acquisition_audits_org_created_idx
    ON fundamental.source_acquisition_audits(organization_id, created_at DESC);

INSERT INTO fundamental.schema_migrations(version)
VALUES ('fundamental-metadata-v2')
ON CONFLICT (version) DO NOTHING;
