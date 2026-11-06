# Issue 321: Immutable Data Release Activation

Status: design checkpoint for issue #321. The target-state rules in
`fundamental-enterprise-grade-target-state.md` and the accepted issue
specification remain authoritative.

## Problem

Fundamental currently publishes immutable snapshots, facts, mappings, and
calculation replay manifests, but it has no durable profile-scoped data release
pointer. Snapshot resolution searches all stored snapshots. Calculation inputs
pin a snapshot, while their provenance does not identify a data release that
binds the snapshot to its mapping, taxonomy, parser, and quality artifacts.

The existing `ReleaseManifestV1` is a calculation replay manifest. Reusing it
as a serving release would conflate calculation evidence with a deployable data
cohort. `ModelInventory` also has an in-memory model-version pointer; it cannot
coordinate API workers or survive process replacement. Data release activation
therefore needs its own immutable manifest, persistent pointer, and transaction
boundary inside the Fundamental service.

## Caller usage

An ingestion or release runner prepares and validates a candidate outside the
API request path, then publishes the immutable candidate and its verification
evidence through the service-owned release catalog. It does not schedule work
inside an API replica.

An authorized operator reads a profile's active pointer and activates a
validated candidate using compare-and-swap:

```json
{
  "manifest_digest": "<candidate SHA-256>",
  "expected_revision": 4,
  "expected_manifest_digest": "<current SHA-256>",
  "reason": "Approved quarterly source and mapping release"
}
```

The service derives the actor and organization from the signed internal
context. A stale revision returns a stable conflict with the current pointer;
the runner must revalidate before retrying. Rollback names a previously
activated compatible manifest and uses the same compare-and-swap operation.

Snapshot resolution names a release profile. It reads the active pointer and
manifest once, then selects only snapshots in that manifest. The response
returns both the selected snapshot digest and data release manifest digest. A
calculation request carries that immutable digest beside its explicit snapshot
ID; calculations and replay never reread the active pointer. A caller that
supplies only an explicit snapshot keeps the existing explicit-snapshot
semantics, subject to the selected snapshot's compatibility checks.

## Shape

The Fundamental service remains the sole owner of data release state. Add a
`data_releases.py` vertical slice for release contracts and deterministic
validation. `PostgresMetadataStore` remains the persistence adapter and owns the
SQL transactions. `FundamentalApplication` coordinates release resolution and
calculation pinning; `app.py` only assembles typed routes and the service.

The data release manifest is separate from the calculation replay manifest:

```python
class FactRefV1(StrictModel):
    fact_id: str
    fact_digest: str

class SnapshotRefV1(StrictModel):
    snapshot_id: str
    manifest_digest: str
    facts: tuple[FactRefV1, ...]
    fact_set_digest: str

class MappingRefV1(StrictModel):
    mapping_id: str
    mapping_digest: str

class ArtifactRefV1(StrictModel):
    artifact_id: str
    content_hash: str
    media_type: str
    role: str

class DataReleaseManifestV1(StrictModel):
    profile_id: str
    release_id: str
    created_at: datetime
    snapshot_refs: tuple[SnapshotRefV1, ...]
    mapping_refs: tuple[MappingRefV1, ...]
    taxonomy_refs: tuple[ArtifactRefV1, ...]
    parser_version: str
    quality_profile_digest: str
    required_fields: tuple[str, ...]
    artifact_refs: tuple[ArtifactRefV1, ...]
    manifest_digest: str

class DataReleaseVerificationV1(StrictModel):
    manifest_digest: str
    verification_suite_digest: str
    passed_gate_ids: tuple[str, ...]
    evidence_refs: tuple[ArtifactRefV1, ...]
    mapping_reviews: tuple[MappingReviewEvidenceV1, ...]
    verification_digest: str

class MappingReviewEvidenceV1(StrictModel):
    mapping_id: str
    mapping_digest: str
    author_id: str
    reviewer_id: str
    reviewed_at: datetime
    evidence_refs: tuple[ArtifactRefV1, ...]
    fixture_digest: str
    signature: str

class ActiveDataReleaseV1(StrictModel):
    profile_id: str
    manifest_digest: str
    revision: int
    activated_at: datetime

class DataReleaseRepository(Protocol):
    def publish_candidate(self, manifest, verification) -> None: ...
    def get_active(self, profile_id: str) -> ActiveDataReleaseV1 | None: ...
    def compare_and_swap(self, command, actor, correlation_id) -> ActiveDataReleaseV1: ...

class DataReleaseService:
    def validate_candidate(self, manifest) -> DataReleaseVerificationV1: ...
    def activate(self, command, actor, correlation_id) -> ActiveDataReleaseV1: ...
    def rollback(self, command, actor, correlation_id) -> ActiveDataReleaseV1: ...
    def resolve_snapshot(self, request) -> PinnedSnapshotV1: ...
```

The review attestation is signed by a configured trusted reviewer key. The
release runner records the candidate publisher as `author_id`; the validator
requires a different reviewer identity and binds the mapping digest, scoped
evidence, and fixture digest into the signature. The existing mapping schema
stays unchanged so v2 applications can continue reading stored mappings during
rollout.

The repository sketch deliberately exposes one atomic pointer operation rather
than separate read, update, and audit methods. Candidate validation checks
manifest and artifact hashes, referenced snapshot and fact membership,
parser/taxonomy compatibility, quality evidence, and mapping approval. An
unresolved valuation-critical extension mapping cannot pass. Its approved
mapping must include scoped evidence and an independent reviewer; the
activation actor is recorded separately.

The additive PostgreSQL migration creates `data_release_manifests`,
`data_release_verifications`, `active_data_release_pointers`,
`data_release_activation_audit`, and a `schema_capabilities` marker. The active
row is keyed by profile and carries a monotonic revision. A pointer change and
its append-only audit row commit in one transaction. Readers use one query to
resolve pointer and immutable manifest, so each request pins one complete
release even while another transaction activates a candidate.

Migration 003 must remain readable by the existing #312 v2 application while
old and new replicas overlap. That binary rejects a newer value in
`schema_migrations`; the additive migration therefore leaves the v2 contract
marker intact and records the new capability separately. New code checks that
capability before release operations. DDL is idempotent, and no old table or
column is renamed or removed in this issue.

The request cache key includes the release manifest digest, snapshot manifest
digest, fact-set digest, mapping package digest, taxonomy and parser versions,
quality profile digest, identity, valuation timestamp, and required fields. The
active pointer is read before cache lookup. A new release therefore creates a
new cache namespace without a global flush; an in-flight request retains the
key and manifest it already pinned. Calculation evidence and replay dependency
hashes include the data release manifest digest.

The release runner performs read-only candidate validation, golden-fixture
checks, offline replay, and available SEC EFM/DQC checks before publishing a
candidate. The API has no background release job. Activation and rollback
record actor, organization, correlation ID, reason, old and new digests, and
revision in the append-only audit table. Metrics expose activation and rollback
counts, pointer conflicts, active release age, and request latency.

## Where changes belong

- `fundamental-service/src/fundamental_service/data_releases.py`: immutable
  data-release contracts and candidate validation.
- `fundamental-service/src/fundamental_service/metadata.py` and
  `migrations/003_data_release_activation.sql`: candidate persistence, pointer
  CAS, audit transaction, and capability readiness.
- `fundamental-service/src/fundamental_service/application/service.py`: pin one
  release during resolution and bind the digest into calculation evidence.
- `fundamental-service/src/fundamental_service/app.py` and
  `interface/transport.py`: typed read, activate, rollback, and snapshot
  resolution boundaries; activation authorization is a separate organization
  allowlist.
- `fundamental-service/src/fundamental_service/release_runner.py`: separately
  operated candidate validation and publication; no API replica scheduler.
- `fundamental-service/tests/`: PostgreSQL CAS, reader/publisher races,
  crash/restart recovery, cache isolation, mapping review, replay pinning, and
  old/new schema overlap.

Dependency direction is `HTTP composition -> FundamentalApplication ->
DataReleaseService -> DataReleaseRepository`; the repository adapter owns SQL.
The deterministic calculator receives only the already pinned request and
never resolves active state or performs I/O.

## Alternatives considered

- Put the active pointer in `ModelInventory` or process memory. This keeps a
  small interface but exposes process-local state to every replica, loses the
  pointer on restart, and cannot serialize competing publishers or rollback
  audit. It fails the ownership and concurrency requirements.
- Store the active pointer in deployment configuration. This exposes pointer
  changes to every deployment file and requires replica restart or
  configuration polling. It provides no transactional compare-and-swap with
  manifest publication and can split replicas across releases.
- Reuse `ReleaseManifestV1` from `replay.py`. This makes serving activation
  depend on calculation-specific fields and mixes mutable pointer lifecycle
  with immutable per-calculation replay evidence.

The PostgreSQL-backed data-release slice is the only considered shape that
keeps profile state durable, lets all replicas agree through one transaction,
and preserves calculation replay as an immutable record.

## Synthesis decision

Select the PostgreSQL-backed `DataReleaseService` slice. It hides manifest
validation, pointer fencing, and audit ordering behind a small service and
repository surface while leaving snapshot storage and calculation ownership in
their existing modules. The design was compared by the primary executor; the
repo instruction against delegating research precludes a multi-runner design
panel for this issue.

## Tradeoffs accepted

- We accept one PostgreSQL pointer read per active snapshot resolution in
  exchange for an authoritative cross-process release selection.
- We accept keeping old immutable manifests and evidence readable in exchange
  for replay and rollback without rebuilding or rewriting history.
- We accept a separate release runner entrypoint in exchange for keeping
  candidate construction and expensive validation off serving replicas.
- We accept a capability marker alongside the existing v2 schema marker in
  exchange for old/new application overlap without making the current v2
  binary reject the additive migration.

## Implementation reconciliation

The additive migration, immutable manifest and verification persistence,
transactional pointer CAS, append-only activation audit, and PostgreSQL
idempotency/concurrency checks are implemented in the current issue branch.
Candidate persistence requires a trusted verification and independent mapping
review signature. Runtime deployment can provide those public keys through
`FUNDAMENTAL_DATA_RELEASE_TRUST_ROOTS_FILE`; an unset path keeps candidate
publication fail-closed. The operations Compose file mounts a local-only
development trust-root fixture and is not a production trust configuration.

Serving behavior remains unimplemented: there is no typed release publish or
activation route, request-level pinned release contract, release-aware cache,
or end-to-end fault/recovery/overlap/load evidence yet. These remain required
by issue #321 and are not considered verified by the persistence checkpoints.

## Open questions and risks

- The issue does not set numeric latency or soak thresholds. The acceptance
  record must declare the local verification SLO before running load tests and
  report observed availability, p95 latency, activation duration, pointer
  conflicts, rollback behavior, and release freshness.
- Existing `CanonicalMappingV1` records a reviewer but not a separate mapping
  author. Candidate validation can prove approval evidence exists and compare
  the reviewer with the activation actor, but cannot prove reviewer
  independence from an unrecorded author. The release runner must retain scoped
  review evidence; if implementation needs an author field or signed
  attestation, record the contract change here before coding it.

## Next implementation step

Implement the typed service boundary and request-level release pinning on top
of the verified repository contract. Keep candidate validation and publication
outside API replica scheduling, and preserve the active pointer on every
validation or persistence failure.
