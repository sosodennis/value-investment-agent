# Organization provider secret lifecycle

This runbook is the operational contract for the organization-owned Search and
LLM provider credentials introduced by #213, #214, and #215. It covers the two
service encryption keys and the provider keys encrypted by them. It does not
define email, SMTP, browser push, or another external notification channel.

## Ownership and storage

The platform owner generates and stores one Fernet key per environment for
each service:

- `LLM_PROVIDER_ENCRYPTION_KEY` protects LLM deployment and import ciphertext.
- `SEARCH_PROVIDER_ENCRYPTION_KEY` protects Search provider-key ciphertext.
- `LLM_PROVIDER_SERVICE_TOKEN` authenticates backend calls to the LLM provider
  service.
- `SEARCH_SERVICE_TOKEN` authenticates backend calls to the Search service.

Production must provide both service tokens to the backend and their matching
provider services. The production Compose overlay rejects missing values and
must never inherit the local development fallback token. Generate independent
high-entropy service tokens per environment and store them with the other
deployment secrets.

Generate keys with the service runtime, never with a copied example value:

```sh
uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Store each value in the environment secret store used by the deployment and
keep its backup in a separate access-controlled location. Never put a raw
provider key or Fernet key in Git, an issue, a PR, a fixture, a log, a metric,
or a trace. The database contains only Fernet ciphertext. API responses expose
labels, suffixes, fingerprints, status, and timestamps.

Startup is fail-closed. A missing or malformed required service key, a legacy
provider table, or an unsupported provider schema version prevents readiness.
The service error identifies the missing configuration or schema condition but
never includes a secret value.

## Provider-key rotation and revocation

To rotate one OpenRouter or Search credential, add and test the replacement in
the verified organization, confirm a healthy provider test, then replace the
old key. LLM replacement keeps the old deployment during the configured grace
window so in-flight requests can finish; the cleanup worker removes it after
`LLM_KEY_REPLACEMENT_GRACE_SECONDS`. Search replacement resets its lease and
cooldown state. Delete or disable the old key after the replacement is healthy.

Revocation takes effect at the next dispatch boundary: delete the
organization-owned key or disable it. A revoked key is not eligible for new
Search leases or LLM dispatches. A request that already sent the key to an
upstream provider cannot be cancelled by the control plane; record that
boundary in incident evidence. Provider health failures and upstream responses
remain redacted; an account, workspace, model, or upstream-provider limit does
not rotate a key automatically.

## Encryption-key rotation

Encryption-key rotation is a maintenance operation, separate from provider-key
replacement:

1. Freeze provider-key mutations and take a verified database backup.
2. Generate a new Fernet key and store it in the environment secret store,
   but keep the old key available only to the rotation operator.
3. Stop the affected service and run its checked-in rotation command with the
   old and new keys. The command requires `--confirm`, re-encrypts every target
   organization ciphertext in one transaction, and prints only a row count.
4. Start the service with the new key and verify readiness, organization
   isolation, a provider test, and one successful inference or search request.
5. Verify the backup and rotation evidence, then revoke access to the old key.

Search rotation:

```sh
cd search-service
SEARCH_CONTROL_DATABASE_URL="$SEARCH_CONTROL_DATABASE_URL" \
SEARCH_OLD_ENCRYPTION_KEY="$OLD_KEY" \
SEARCH_NEW_ENCRYPTION_KEY="$NEW_KEY" \
uv run python scripts/rotate_encryption_key.py --confirm
```

LLM rotation:

```sh
cd llm-provider-service
LLM_OLD_ENCRYPTION_KEY="$OLD_KEY" \
LLM_NEW_ENCRYPTION_KEY="$NEW_KEY" \
uv run python scripts/rotate_encryption_key.py --confirm
```

If any ciphertext cannot be decrypted, the transaction rolls back. Keep the
old key active, restore from the verified backup if necessary, and treat the
event as an incident. Do not delete the old key until post-rotation checks
pass.

## Incident response

If a provider key or service encryption key may be exposed:

1. Disable or delete the affected organization provider keys at the upstream
   provider and in this system.
2. Rotate the service encryption key using the maintenance procedure above.
3. Preserve the redacted audit event, backup identifier, affected environment,
   and exact verified commit. Do not record the secret itself.
4. Check logs, traces, metrics, fixtures, and issue evidence with the secret
   redaction scanner before sharing evidence.
5. Record recovery and remaining risk in the incident issue.

## Disposable reset and rebuild

Local and staging PostgreSQL/Redis data is disposable only when the operator
has confirmed its project name and backup scope. Rebuild the target schema by
stopping that Compose project and removing only its volumes:

```sh
PROJECT=value-investment-agent-staging
docker compose --env-file .env.staging -p "$PROJECT" down --volumes
docker compose --env-file .env.staging -p "$PROJECT" up -d --build
docker compose --env-file .env.staging -p "$PROJECT" ps
```

The first provider-service readiness check creates only the version 1
organization schema. Re-run the staging smoke and the secret-redaction scan;
record the project, reset scope, commit, and results. Never run a global Docker
prune command.

## Retained production data disposition

The inspected local LiteLLM database contained zero provider rows; its retained
volume was preserved and is no longer part of the Compose topology. This is a
local disposition only. Before a production rollout, the production owner must
record a backup and row-count check for any legacy `llm_provider_*` or
`search_provider_*` table. A production database containing legacy provider
rows is a blocker: stop deployment and link #190 or a replacement blocker with
the approved export/re-key or retained-data decision. The application never
silently drops or backfills those tables.

## Maintenance of this runbook

The platform owner updates this document in the same change as any provider
schema, required secret, rotation/revocation behavior, reset scope, backup
procedure, readiness check, or incident step. After each update, run the
service tests, Compose config validation, a disposable reset/rebuild, provider
failure and redaction checks, and record exact commit evidence. A changed
procedure without matching implementation or evidence is unverified.
