# Fundamental service

This directory contains the independently deployable Fundamental domain service.

Read the [Fundamental service target state](docs/fundamental-enterprise-grade-target-state.md) for the only normative definition of the service's data contracts, model registry, calculations, calibration, provenance, verification, and delivery stages.

Runtime startup, health, auth, deadline, budget, recovery, and Compose checks
are documented in the [operations runbook](docs/operations-runbook.md), which
remains subordinate to the target state.

Production deployments must set `FUNDAMENTAL_MODEL_TRUST_ROOTS_FILE` to a
read-only deployment-owned JSON file containing verifier IDs, workflow
identities, raw Ed25519 public keys, exact source revisions, and verification
suite digests. Missing roots keep `/readyz` at `not_ready`; malformed roots
fail startup. The operations Compose file uses a development-only public key
fixture and must not be used as a production trust root.

The service will own its source snapshots, point-in-time facts, model definitions, deterministic calculations, calibration artifacts, replay, and cache. The existing agent will call the service through a versioned API after the service passes the release gate for its declared coverage profile. The service must not import the existing agent's private implementation or share its valuation database.

## Source preparation command

`fundamental-prepare-source` coordinates source acquisition, trusted release
activation and the existing automatic composer outside the serving API request
path. Run it with the service's configured PostgreSQL, content volume, SEC
validation assets and trust roots:

```sh
fundamental-prepare-source \
  --plan approved-source-plan.json --plan-digest <canonical-plan-sha256> \
  --actor <operator-id> --organization <authorized-organization>
```

The versioned `SourcePreparationPlanV1` pins a source revision, release profile,
model and complete `SecIngestionRequestV1`. Its digest is SHA-256 over the service's
canonical serialization. The command first resolves released evidence. On a miss,
it uses existing SEC acquisition and retention; an already stored snapshot can be
used with `--candidate <trusted-candidate.json>` without another acquisition.
Candidate publication and activation require the configured organizations, release
verification and independent mapping review signatures. This command does not
create review signatures or approve new mappings.

The canonical JSON receipt contains an artifact reference and `wrote`. Read its
metadata and bytes through the authenticated `/v1/artifacts/{artifact_id}` and
`/v1/artifacts/{artifact_id}/content` endpoints. Identical evidence is reused with
`wrote=false`; corrupt or conflicting evidence fails without replacement.

The stored outcome is `release_required` for an acquired but unreleased snapshot,
`blocked` for retained evidence failures, or `approval_required` when the formal
composer prepares an input. To calculate, pass `--approval <approval.json>` with
the caller's explicit approval of that exact prepared input digest. `calculated`
retains the existing calculator's uncertainty report and provenance. The command
does not own a valuation session or job, and it never manufactures caller approval.

The #361 complete-flow acceptance remains pending. Synthetic fixtures prove
coordination and persistence mechanics; they do not certify real issuer mappings,
multi-filing coverage or end-to-end original-filing numerical success. History
thresholds remain null, and supported calculations remain provisional where the
existing composer requires that disposition.

The service consumes the shared `internal.v1` context from
`finance-agent-core/src/shared/internal_services` through the supported Docker
additional build context. Its operation payloads are `{context, input}` and its
responses carry shared correlation/error metadata around a service-owned
`fundamental.v1` result. It never imports agent implementation modules or reads
the agent database/cache.

The parent integration branch is `codex/issue-270-integration` and its dedicated worktree is `../value-investment-agent-issue-270-integration`. Child changes are delivered serially from that tip according to `docs/issue-worktree-lifecycle.md`.

## Independent verification

The fixed release cohort is replayed entirely from captured SEC bytes. It does
not perform provider access:

```sh
uv run --python 3.12 python -m fundamental_service.verification_gate \
  --cohort tests/fixtures/verification/golden_cohort.json \
  --report /tmp/fundamental-verification-report.json
```

The gate compares the production graph with equations maintained in
`src/fundamental_service/verification.py`, checks node tolerances and formula
invariants, exercises monotonicity/metamorphic and mutation sentinels, and
requires machine-readable reasons and missing evidence for every abstention or
degraded case. The engineering cohort is replay evidence only; it is never
used as calibration ground truth.

## Operations verification

The isolated container uses
`compose/verification/docker-compose.issue280-operations.yml` with project
`value-investment-agent-270-integration`. It owns a project-scoped named volume
for snapshots, content, and released artifacts and does not start the unrelated
repository-wide stack.
