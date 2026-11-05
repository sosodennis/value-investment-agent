# Fundamental Service Operations Runbook

This runbook is subordinate to the [Fundamental enterprise-grade target
state](fundamental-enterprise-grade-target-state.md). It describes the runtime
controls for issue #280 and does not change the data, calculation, provenance,
or release policies defined there.

## Start and health

Run only the isolated verification service from the repository root:

```sh
docker compose -p value-investment-agent-270-integration \
  -f compose/verification/docker-compose.issue280-operations.yml up -d --build
docker compose -p value-investment-agent-270-integration \
  -f compose/verification/docker-compose.issue280-operations.yml ps
```

The default host ports are `18080` for the service and `15481` for the
Fundamental-owned PostgreSQL instance; set `FUNDAMENTAL_SERVICE_HOST_PORT` or
`FUNDAMENTAL_POSTGRES_HOST_PORT` when either port is occupied. PostgreSQL stores
the Fundamental metadata schema (`fundamental`) and the named volume stores only
content-addressed bytes. Set `FUNDAMENTAL_SERVICE_DATABASE_URL` and run with
`FUNDAMENTAL_SERVICE_AUTO_MIGRATE=1` for a clean local database. `/livez` is
process liveness and stays free of dependency details. `/readyz` is dependency
readiness and requires the compatible Fundamental schema, content volume, and
service token. It also requires a non-empty model-release trust-root inventory.
Both endpoints return only the `internal.v1` status shape.

Set `FUNDAMENTAL_MODEL_TRUST_ROOTS_FILE` to a read-only deployment-owned JSON
file. Its `verifiers` map pins each verifier ID to a workflow identity, a
base64-encoded raw Ed25519 public key, an exact 40-character source revision,
and a SHA-256 verification-suite digest. The service never receives the
private signing key. Missing roots leave readiness `not_ready`; malformed
configuration fails startup. The verification Compose file mounts the
development-only fixture at this path by default. Set
`FUNDAMENTAL_MODEL_TRUST_ROOTS_HOST_FILE` to replace that host file for local
verification. Never use the development fixture as a production trust root.

Every `/v1/` operation requires `Authorization: Bearer <FUNDAMENTAL_SERVICE_TOKEN>`
and a signed `internal.v1` context in the `{context, input}` body envelope. The
context binds the `fundamental-service` audience, `finance-agent-core` issuer,
principal organization and membership, correlation ID, and absolute deadline.
Error responses use the shared `InternalErrorResponse`; they never include
credentials, provider responses, filesystem paths, or raw filing content.

## SEC ingestion contract

`POST /v1/data/ingestions` is the authenticated, synchronous `fundamental.v1`
SEC acquisition operation. Its strict `input` schema requires the canonical
issuer/security identity, CIK and matching ticker, valuation timestamp,
required field set, approved mapping decision/version references, bounded
filing selector, coverage and legal-use profiles, parser release, taxonomy
manifest/version, and policy version. It does not accept URLs, raw filing
payloads, caller idempotency keys as identity, or local filesystem paths. The
generated OpenAPI schema is the wire-level field contract.

Set `FUNDAMENTAL_SERVICE_INGESTION_ORGANIZATIONS` to a comma-separated list of
organization IDs allowed to acquire SEC evidence. This authority is separate
from normal valuation reads. Set `FUNDAMENTAL_SERVICE_INGESTION_RATE_LIMIT_PER_MINUTE`
for the per-organization request quota and `FUNDAMENTAL_SERVICE_MAX_INGESTION_MS`
for the bounded synchronous budget. The service also paces every EDGAR HTTP
request through a PostgreSQL-backed limiter shared by service processes. It
uses the registered `data.sec.gov` submissions endpoint and `www.sec.gov`
filing archive only, with an identifiable `FUNDAMENTAL_SEC_USER_AGENT`, SEC
Retry-After handling, bounded retries and response sizes, and the original
signed deadline. There is no background queue; callers own retry after a
retryable `INGESTION_IN_PROGRESS` or deadline response.

The deployment must mount a reviewed, immutable offline Arelle taxonomy cache
and set `FUNDAMENTAL_SEC_TAXONOMY_CACHE_DIR`,
`FUNDAMENTAL_SEC_TAXONOMY_MANIFEST_ID`, `FUNDAMENTAL_SEC_TAXONOMY_VERSION`,
and `FUNDAMENTAL_SEC_TAXONOMY_CACHE_SHA256`. Startup composition disables the
ingestion route when these pins or the SEC User-Agent are absent. The runtime
recomputes the cache directory hash and rejects a request whose taxonomy pins
do not match. Do not mount the test taxonomy fixture as production evidence.

The provider returns only a typed snapshot reference, manifest digest,
canonical fact IDs, source hashes, filing metadata, quality, missing evidence,
and version pins. Filing bytes stay in the Fundamental content-addressed
volume. PostgreSQL publishes the immutable snapshot, facts, snapshot/fact
links, and canonical acquisition result in one transaction. A PostgreSQL
advisory lock and acquisition-key uniqueness ensure identical work across
processes has one fetch leader; successful retries reuse the same manifest.
Failed parsing or fact selection can leave unreferenced content-addressed bytes,
but it cannot publish a snapshot or verified fact set. Authorized attempts
record principal, organization, correlation ID, hashes when known, and outcome
in the service-owned audit table.

## Recovery checks

- A missing snapshot or artifact returns `SOURCE_UNAVAILABLE` or a stable
  not-found code. The caller receives an unavailable/degraded result and must
  not calculate locally.
- Restarting the container reconnects to PostgreSQL and reopens the
  content-addressed volume. Metadata publication is immutable and concurrent
  idempotent; retain evidence artifacts and their source dependencies. Rebuild
  a damaged artifact as a new content-addressed generation and preserve the old
  record for audit.
- A missing, stale, or incompatible Fundamental schema keeps `/readyz` in the
  `not_ready` state. Apply the checked-in migration through the service-owned
  migration runner before retrying readiness; do not point the service at Agent
  tables or select a filesystem metadata fallback.
- Disk exhaustion is an operator alert. Stop ingestion, preserve evidence, and
  repair or expand the mounted data volume before publishing another snapshot.
  Do not delete referenced evidence.
- A request over the synchronous sample, forecast, body, rate, or deadline
  budget returns a stable error. There is no server-side job queue.

Inspect `/metrics` for source health, snapshot freshness, cache hit/miss/stale,
calculation latency and budget failures, quality status, abstention,
provenance/replay failures, and provider degradation counters. Metrics are
process diagnostics only and do not replace release evidence or calibration
reports.

## Stop and clean up

```sh
docker compose -p value-investment-agent-270-integration \
  -f compose/verification/docker-compose.issue280-operations.yml down
```

Keep the named volume unless the issue's disposable verification data has been
recorded and a rebuild from captured public snapshots is available. Never use a
global Docker prune command for this service.
