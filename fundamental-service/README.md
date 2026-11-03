# Fundamental service

This directory contains the independently deployable Fundamental domain service.

Read the [Fundamental service target state](docs/fundamental-enterprise-grade-target-state.md) for the only normative definition of the service's data contracts, model registry, calculations, calibration, provenance, verification, and delivery stages.

The service will own its source snapshots, point-in-time facts, model definitions, deterministic calculations, calibration artifacts, replay, and cache. The existing agent will call the service through a versioned API after the service passes the release gate for its declared coverage profile. The service must not import the existing agent's private implementation or share its valuation database.

The first runtime slice freezes the `internal.v1` context and `fundamental.v1` data/calculation contracts in `src/fundamental_service`. It remains independent of `finance-agent-core`; later slices add source ingestion, facts, policies, deterministic calculations, replay, operations, and the typed agent client.

The parent integration branch is `codex/issue-270-integration` and its dedicated worktree is `../value-investment-agent-issue-270-integration`. Child changes are delivered serially from that tip according to `docs/issue-worktree-lifecycle.md`.
