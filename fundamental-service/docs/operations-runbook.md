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
The response keeps the shared `internal.v1` status fields and adds a
non-secret Fundamental capability map. In particular,
`capabilities.identity_resolution_configured` means the deployment has a
configured SEC identity-resolution use case and can attempt issuer resolution;
it does not mean that a ticker has already resolved or that a valuation snapshot
is ready.

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

The pinned Arelle/EFM/DQC worker runs in a child process and shares the
Fundamental service cgroup with the API process. The parser applies a child
virtual-memory budget through `FUNDAMENTAL_SEC_PARSER_MAX_MEMORY_BYTES` and
limits concurrent workers through `FUNDAMENTAL_SEC_PARSER_MAX_CONCURRENCY`.
The defaults are 768 MiB and one worker. A resource or concurrency refusal
returns a retryable typed error and publishes no snapshot or facts. The
verification Compose stack still needs enough cgroup memory for the API,
PostgreSQL client, and the selected parser budget.

The deployment must mount a reviewed, immutable offline Arelle taxonomy cache
and set `FUNDAMENTAL_SEC_TAXONOMY_CACHE_DIR`,
`FUNDAMENTAL_SEC_TAXONOMY_MANIFEST_ID`, `FUNDAMENTAL_SEC_TAXONOMY_VERSION`,
and `FUNDAMENTAL_SEC_TAXONOMY_CACHE_SHA256`. It must also mount the pinned
EDGAR validation plugin, XULE plugin, and DQC ruleset and set their paths and
SHA-256 values through `FUNDAMENTAL_SEC_EDGAR_PLUGIN_*`,
`FUNDAMENTAL_SEC_XULE_PLUGIN_*`, and `FUNDAMENTAL_SEC_DQC_RULESET_*`. Startup
composition disables the ingestion route when any of these pins or the SEC
User-Agent are absent. The runtime recomputes every directory/file hash and
rejects a request whose taxonomy or validation pins do not match. Do not mount
the test taxonomy or validation fixtures as production evidence.

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

## Sign an independent mapping review

After an authorized independent reviewer has completed the semantic review, use
the service's operator command to sign their existing statement. The statement
uses `MappingReviewStatementV1`: mapping ID/digest, author/reviewer IDs, an explicit
timezone-aware `reviewed_at`, retained `evidence_refs`, and the canonical JSON
fixture's `fixture_digest`. It contains no signature. The mapping must already be
approved and name the same reviewer and review time. The signer does not create
approvals, keys, reviewer identities, trust roots or missing evidence.

Use the deployment's existing immutable trust-roots file and the reviewer's
Ed25519 private key in unencrypted PKCS8 PEM format. Keep the private key and the
generated evidence outside Git. The command checks the mapping digest, canonical
fixture digest and each retained evidence artifact's hash, media type, valid
status and evidence retention before signing. The key must match that reviewer's
configured trusted public key, and reviewer and author must differ.

```sh
fundamental-sign-mapping-review \
  --statement /reviews/statement.json \
  --mapping /reviews/mapping.json \
  --fixture /reviews/fixture.json \
  --trust-roots /run/config/data-release-trust-roots.json \
  --private-key /run/secrets/mapping-reviewer.pem \
  --source-revision "$VERIFIED_IMPLEMENTATION_COMMIT"
```

By default, this command uses the same `FUNDAMENTAL_SERVICE_DATABASE_URL` and
`FUNDAMENTAL_SERVICE_DATA_ROOT/content` as the running service. The database must
already have the installed schema; signing does not run migrations, seed policies
or activate releases. It closes database resources after success or failure.
Service readers and the existing export/restore commands can retrieve the signed
artifact directly from that data plane. For an offline canary artifact store,
pass `--artifacts-root /reviews/offline-artifacts` explicitly. Both adapters use
the same signed bytes, content identity and publication receipt contract.

The canonical receipt records the supplied implementation revision, input/output
digests and artifact publication. The signed artifact uses the unchanged
`MappingReviewEvidenceV1` contract and a content-derived ID. It is published
through the existing atomic immutable store; rerunning the same inputs, including
after process restart, returns `publication.wrote=false` without rewriting the
artifact or index. Failures return exit 2 with a stable error code and do not
publish signed evidence or print private keys, source bytes or validation values.
The statement's time is supplied by the reviewer, never generated by the command.

This command does not run semantic review or the release canary, activate a
release, approve financial policy, supply caller approval, or verify an estimated
history threshold. Continue with the existing signed release verification and
canary workflow; an authentic signature alone does not establish those gates.

## Recovery checks

### Export and restore the persistent data plane

`fundamental-persistence` is an offline operator command. Stop every API and
acquisition/preparation writer using the source database and content root before
export, and keep all writers off the target until restore completes. The command
locks the Fundamental tables and rejects observed content changes. It does not
provide a coordinated live backup across independently running filesystem
writers. Run it with the same installed release, migrations and PostgreSQL major
version as the source. It uses `FUNDAMENTAL_SERVICE_DATABASE_URL` and
`FUNDAMENTAL_SERVICE_DATA_ROOT`; neither credentials nor source bytes are printed.

```sh
fundamental-persistence export \
  --source-revision "$VERIFIED_IMPLEMENTATION_COMMIT" \
  --destination /backups/fundamental
```

The receipt identifies `/backups/fundamental/<manifest_digest>/manifest.json`.
Copy the complete directory to retained storage outside the disposable service
volume. The canonical manifest pins the implementation revision, migration and
schema digests, PostgreSQL major version, every table's columns/row count/file
digest, and every source/content file's digest and length. Source bytes from
failed ingestion are included even if registration was interrupted. Missing or
corrupt snapshot/fact/artifact source bytes refuse publication. Table values are
exported as sorted canonical JSON lines containing PostgreSQL text values;
timestamps retain their original UTC values. Operational audit rows remain part
of the backup, separate from valuation identity.

The complete backup is staged, verified and atomically renamed to its digest.
Re-exporting identical state and revision returns `wrote=false` without touching
the existing directory. An existing corrupt backup is rejected, never replaced.
Record the receipt and exact command in acceptance evidence. Export is not an
independent mapping review or a release signature.

Point the environment at a **new, isolated database and content root**, then use
the recorded digest, obtained independently of the backup's current contents:

```sh
fundamental-persistence restore \
  --bundle /backups/fundamental/<manifest_digest> \
  --manifest-digest <manifest_digest>
```

Restore checks the entire inventory, referenced bytes, schema and runtime
compatibility before importing rows. It initializes the owned schema only when
absent. An existing target must be empty apart from schema bootstrap records, or
already contain exactly the backed-up metadata; unrelated data is refused. The
content root may contain only a matching subset of the backup's objects. Bytes
are published atomically before a single metadata transaction imports all rows
in foreign-key order. Failure rolls back the metadata transaction; already
restored matching bytes are retained for retry. Temporary copy bytes stay in
`.restore-pending`, which is outside the published
content inventory; a killed copy cannot publish a partial object or block retry.
Uncommitted staging bytes are retained locally and excluded from export.
The acquisition-audit sequence continues beyond restored IDs. The transaction verifies the restored table
digests before commit. Repeating a complete restore returns `wrote=false` and
does not modify existing content files.

Deployment secrets, trust roots, parser/taxonomy assets and service configuration
are not data backup contents. Restore their separately pinned deployment inputs
before starting the service; existing release-trust and caller-approval checks
remain enforced. After restore, check `/readyz`, retrieve a known snapshot and
valuation artifact, and rerun its pinned preparation/calculation. Compare all
source/input/output digests with the recorded evidence. A successful copy alone
does not establish full-flow acceptance.

Automatic FCFF inputs identify `fcff-forecast-composer-v4` in
`provenance.preparation_version`, which participates in the input digest and
caller approval. This composer implements the declared `lease-treatment-v1`:
only current/noncurrent finance lease obligations enter the equity-bridge lease
deduction. Operating lease costs remain in FCFF; operating lease balances remain
required source observations without a second equity deduction. The lease
assumption's formula and fact IDs identify only the finance lease obligations.
Existing artifacts and approvals retain their original identities; prepare and
approve the corrected input before calculating it. Unknown lease roles still
abstain, and history thresholds remain unset.

Composer v4 retains the isolation of historical metrics, automatic preparation, manual
overrides and uncertainty estimation from caller/thread Decimal state. Calculator
and uncertainty execution use the declared `decimal-50-end-of-year-v1` policy:
50 digits, HALF_EVEN, exponent bounds -999999 to 999999, clamp 0, and traps for
InvalidOperation, DivisionByZero and Overflow. Each synchronous boundary gets a
fresh local context, restores caller settings/flags even on refusal, and never
changes the importing thread's context. Same-runtime result bytes under the
previous intended 50-digit context remain unchanged for the same calculator inputs.
The preparation version changes the prepared input identity, so existing approvals
cannot authorize a newly prepared v4 input. The prior target-table precision34 was inconsistent with the released
model inventory; moving to 34 requires a separately versioned numerical/model
policy and replay evidence. Stored artifacts are never rewritten.

Requirements profiles `fcff-valuation-requirements-v2` and
`transition-fcff-valuation-requirements-v2` replace the precomputed numeric
`dilutive_instruments` input with a release-bound award inventory. Raw observations
use `equity_award_quantity`, `equity_award_unrecognized_compensation`, and, for
options, `equity_award_exercise_price`. Each class retains its original facts and
dimensions. An inventory cannot count equivalent contexts twice or combine a
consolidated total with its class components.

Original parser scope remains intact: an undimensioned observation may retain
`security_scope=unspecified`; an `AwardTypeAxis` observation may retain
`security_scope=segmented`. The signed inventory binds those observations to the
snapshot's reviewed security. Other security IDs, unknown scopes, and stock-class
or entity dimensions remain unsupported. Currency for a divided monetary unit
comes from its numerator (`iso4217:USD/xbrli:shares` retains `USD` and the exact
original unit); source facts are not rewritten to resemble prepared inputs.

Publish canonical `EquityDilutionEvidenceV1` as an artifact with role
`equity-dilution-evidence-v1`, and include the quote's original bytes as an artifact
with role `equity-dilution-quote-source-v1` in the same signed data release. The
bundle binds one snapshot manifest, issuer/security/currency, complete reviewed
inventory, dated quote and explicit versioned freshness policy. Every inventory
fact must match the release's reviewed fact and mapping; every released award
observation must appear in the inventory. The read-only release canary and serving
path reject mismatches and missing source bytes. The formal composer applies the
treasury-stock method under the existing Decimal policy and preserves per-class
anti-dilution exclusions. Unknown performance conditions, missing inventory or
quote, stale/future evidence and unsupported share scope refuse per-share preparation.
The full bundle digest participates in the prepared input and caller approval;
equal numerical share counts do not make different quote evidence interchangeable.
These contracts provide no independent review or release authority themselves.

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
