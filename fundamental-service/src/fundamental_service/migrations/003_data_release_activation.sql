CREATE TABLE IF NOT EXISTS fundamental.schema_capabilities (
    capability_id TEXT PRIMARY KEY,
    installed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

INSERT INTO fundamental.schema_capabilities(capability_id)
VALUES ('data-release-activation-v1')
ON CONFLICT (capability_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS fundamental.data_release_manifests (
    manifest_digest TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    release_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT data_release_manifest_digest_sha256
        CHECK (manifest_digest ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS fundamental.data_release_verifications (
    manifest_digest TEXT PRIMARY KEY
        REFERENCES fundamental.data_release_manifests(manifest_digest),
    verification_digest TEXT NOT NULL,
    payload JSONB NOT NULL,
    verified_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT data_release_verification_digest_sha256
        CHECK (verification_digest ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS fundamental.active_data_release_pointers (
    profile_id TEXT PRIMARY KEY,
    manifest_digest TEXT
        REFERENCES fundamental.data_release_manifests(manifest_digest),
    revision BIGINT NOT NULL DEFAULT 0 CHECK (revision >= 0),
    activated_at TIMESTAMPTZ,
    CONSTRAINT active_data_release_pointer_state
        CHECK ((revision = 0 AND manifest_digest IS NULL AND activated_at IS NULL)
            OR (revision > 0 AND manifest_digest IS NOT NULL AND activated_at IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS fundamental.data_release_activation_audit (
    command_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN ('activate', 'rollback')),
    expected_revision BIGINT NOT NULL CHECK (expected_revision >= 0),
    expected_manifest_digest TEXT,
    from_manifest_digest TEXT
        REFERENCES fundamental.data_release_manifests(manifest_digest),
    to_manifest_digest TEXT NOT NULL
        REFERENCES fundamental.data_release_manifests(manifest_digest),
    actor_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (length(reason) > 0),
    resulting_revision BIGINT NOT NULL CHECK (resulting_revision > expected_revision),
    activated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT release_audit_expected_pointer_state
        CHECK ((expected_revision = 0 AND expected_manifest_digest IS NULL)
            OR (expected_revision > 0 AND expected_manifest_digest IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS data_release_activation_history_idx
ON fundamental.data_release_activation_audit
    (profile_id, to_manifest_digest, activated_at DESC);
