# Fundamental service

This directory contains the independently deployable Fundamental domain service.

Read the [Fundamental service target state](docs/fundamental-enterprise-grade-target-state.md) for the only normative definition of the service's data contracts, model registry, calculations, calibration, provenance, verification, and delivery stages.

Runtime startup, health, auth, deadline, budget, recovery, and Compose checks
are documented in the [operations runbook](docs/operations-runbook.md), which
remains subordinate to the target state.

The service will own its source snapshots, point-in-time facts, model definitions, deterministic calculations, calibration artifacts, replay, and cache. The existing agent will call the service through a versioned API after the service passes the release gate for its declared coverage profile. The service must not import the existing agent's private implementation or share its valuation database.

The first runtime slice freezes the `internal.v1` context and `fundamental.v1` data/calculation contracts in `src/fundamental_service`. It remains independent of `finance-agent-core`; later slices add source ingestion, facts, policies, deterministic calculations, replay, operations, and the typed agent client.

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
