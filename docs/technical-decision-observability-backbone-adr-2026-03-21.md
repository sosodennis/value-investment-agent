# Technical Decision Observability Backbone ADR

Date: 2026-03-21
Status: Accepted
Owner: Technical Agent Domain

## Decision Summary

We will implement a new agent-local technical capability named `decision_observability` to support:
- append-only `prediction_events`
- delayed `outcome_paths` labeling
- internal monitoring read models
- calibration observation building for the existing Technical calibration domain

This capability will live under:
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/technical/subdomains/decision_observability`

It will not be placed under `calibration`, and it will not be extracted into a cross-agent shared infrastructure in phase 1.

The source of truth will be:
- `prediction_events`
- `raw outcome paths`

Production-facing labels will be stored as governed approved snapshots, not as the only truth layer.

## Context

The Technical domain has already implemented the core P1 quant context stack:
- volatility regime
- liquidity proxy
- normalized distance
- cross-timeframe alignment

It also has an evidence layer, semantic readout, and a calibration subdomain. However, it does not yet have an enterprise-grade backbone to:
- persist each decision event
- join delayed outcomes
- support ongoing monitoring
- feed reliable calibration observations from runtime truth data

This creates a gap between:
- deterministic runtime scoring
- enterprise monitoring and model governance expectations

The architecture must stay aligned with the repo's current standards:
- keep code agent-local first
- respect subdomain boundaries
- avoid premature shared infrastructure
- avoid avoidable `object` runtime contracts

## Drivers

### Business and engineering drivers

- We need a stable event ledger for Technical decision outputs.
- We need delayed outcome labeling to measure real-world hit behavior.
- We need monitoring before a larger calibration program.
- We need a path that fits the current codebase and does not require a platform rewrite.

### Governance and enterprise drivers

- Ongoing monitoring and outcomes analysis are expected in model risk governance.
- Calibration should be downstream from observed outcomes, not guessed from internal score magnitude alone.
- Decision outputs must be reproducible and attributable to a concrete runtime version and context.

Supporting references:
- [Federal Reserve SR 11-7](https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm)
- [Google MLOps: Continuous delivery and automation pipelines in machine learning](https://docs.cloud.google.com/architecture/mlops-continuous-delivery-and-automation-pipelines-in-machine-learning)
- [AWS SageMaker Model Quality](https://docs.aws.amazon.com/sagemaker/latest/dg/model-monitor-model-quality.html)
- [AWS SageMaker Ground Truth Merge](https://docs.aws.amazon.com/sagemaker/latest/dg/model-monitor-model-quality-merge.html)

## Decision

### 1. New subdomain placement

Create a new sibling subdomain:
- `technical/subdomains/decision_observability`

This subdomain will own:
- event registry
- outcome labeling
- monitoring read models
- calibration observation builders

`calibration` remains a downstream consumer of observability data. It does not own event capture or delayed labeling.

### 2. Truth model

The canonical truth model will be three-layered:

1. `technical_prediction_events`
2. `technical_outcome_paths`
3. `technical_approved_label_snapshots`

Rules:
- `prediction_events` are append-only.
- `outcome_paths` are append-only.
- `approved_label_snapshots` are governed production-facing projections, not base truth.

### 3. Raw outcomes vs labels

Base truth must preserve raw continuous metrics. Therefore:
- `technical_outcome_paths` stores raw metrics such as `forward_return`, `mfe`, `mae`, and `realized_volatility`
- canonical boolean hit or miss must not be the only stored truth

We will use a dual-mode label lifecycle:
- research and ad-hoc analysis: query-time or view-based derived labels
- approved production labels: persisted governed snapshots

### 4. Snapshot structure

Approved production labels will be stored in a DB table, not only as external artifacts.

`technical_approved_label_snapshots` will use:
- relational metadata for governance and filtering
- JSON or JSONB payload for flexible label contents

Required relational metadata includes:
- `event_id`
- `agent_source`
- `label_family`
- `label_method_version`
- `approved_at`
- `approved_by`
- `definition_hash`

This keeps production labels queryable and governable without forcing wide-table schema churn.

### 5. Event payload requirements

Phase 1 prediction events must store more than final direction alone.

Required event content includes:
- final direction
- raw score or confidence inputs
- setup reliability or equivalent quality summary
- quant context snapshot
- artifact references
- logic and feature contract versions

Rationale:
- future monitoring and calibration need to answer not just whether the model was wrong, but under which market context it was wrong

### 6. Horizon policy

Phase 1 will strictly standardize supported horizons to:
- `1d`
- `5d`
- `20d`

These values are fixed enumerations for the first implementation and must not be agent-generated free text.

### 7. ID and schema strategy

Phase 1 will not block on `UUIDv7`.

Decision:
- keep a stable `event_id`
- keep a separate `event_time`
- design schema to be partition-ready
- do not commit to day-1 partitioning

We explicitly reject the claim that `UUIDv7` alone solves PostgreSQL partition and foreign-key tradeoffs. It is an optional optimization, not a prerequisite architectural decision.

Supporting references:
- [RFC 9562 UUID Version 7](https://www.ietf.org/rfc/rfc9562)
- [PostgreSQL Table Partitioning](https://www.postgresql.org/docs/current/ddl-partitioning.html)
- [PostgreSQL UUID Functions](https://www.postgresql.org/docs/current/functions-uuid.html)

### 8. Integrity strategy

Phase 1 will keep DB-level foreign key integrity where it is practical and low-cost.

Decision:
- do not prematurely drop DB foreign keys in favor of logical-only integrity
- reassess only when measured scale, retention, or partitioning pressure makes the tradeoff necessary

Supporting reference:
- [PostgreSQL Constraints](https://www.postgresql.org/docs/current/ddl-constraints.html)

### 9. Monitoring delivery scope

Phase 1 monitoring will provide SQL read models for internal use only.

Decision:
- no frontend dashboard commitment in phase 1
- no public API commitment in phase 1
- first consumers are internal Python scripts, notebooks, and operational queries

This avoids premature productization while the monitoring semantics are still settling.

### 10. Labeling scheduler strategy in Docker environments

Yes, this works with Docker.

The chosen phase 1 operating model is:
- daily scheduled job
- manual replay script for backfill and recovery
- not workflow-integrated immediate triggering

In a Docker-based deployment, the recommended execution pattern is:
- keep the labeling worker as a one-off Python command
- trigger it from a dedicated scheduler container
- run `supercronic` inside that scheduler container as the only accepted phase 1 scheduler runtime
- keep the main `backend` API container single-purpose

Phase 1 scheduling guardrails:
- do not use host cron as a supported deployment mode
- do not embed a long-running Python scheduler loop into the API container
- do not introduce APScheduler or another stateful in-process scheduler in phase 1
- keep scheduling logic dumb and keep business logic inside a single entrypoint such as `run_labeling_once`

Why:
- this keeps deployment fully container-native
- this avoids scheduler compatibility branches and environment drift
- this keeps logs, signals, and environment handling aligned with container operations
- this preserves a clean separation between scheduling and labeling business logic
- this keeps future migration to Kubernetes `CronJob` straightforward because the scheduled unit remains a one-off command

Supporting references:
- [Docker best practices](https://docs.docker.com/build/building/best-practices/)
- [Docker multi-service container guidance](https://docs.docker.com/engine/containers/multi-service_container/)
- [Supercronic](https://github.com/aptible/supercronic)
- [Kubernetes CronJob](https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/)

## Detailed Architectural Shape

### Subdomain layout

Recommended package structure:
- `domain`
- `application`
- `infrastructure`
- `interface`

Recommended internal owners:
- `event_registry_service`
- `outcome_labeling_service`
- `monitoring_read_model_service`
- `calibration_observation_builder_service`

### Layer ownership

- `domain`
  - deterministic event and outcome concepts
  - raw outcome calculations
  - approved snapshot semantics
  - calibration observation transformation
- `application`
  - use-case ports
  - runtime orchestration boundaries
- `interface`
  - DTOs and read-model contracts
- `infrastructure`
  - repositories
  - ORM persistence
  - worker runtime adapter
  - scheduler-facing execution hooks

## Data Model Decisions

### `technical_prediction_events`

Purpose:
- append-only record of each falsifiable technical decision event

Minimum contents:
- `event_id`
- `agent_source`
- `event_time`
- `ticker`
- `timeframe`
- `horizon`
- `direction`
- `raw_score`
- `confidence`
- `reliability_level`
- `logic_version`
- `feature_contract_version`
- `run_type`
- `artifact_refs`
- `quant_context_payload`

### `technical_outcome_paths`

Purpose:
- append-only outcome resolution table

Minimum contents:
- `event_id`
- `resolved_at`
- `forward_return`
- `mfe`
- `mae`
- `realized_volatility`
- `labeling_method_version`
- `data_quality_flags`

### `technical_approved_label_snapshots`

Purpose:
- governed production label layer

Minimum contents:
- `snapshot_id`
- `event_id`
- `agent_source`
- `label_family`
- `label_method_version`
- `approved_at`
- `approved_by`
- `definition_hash`
- `labels_payload`

## Integration Decisions

### Runtime event write path

Prediction-event registration should occur after:
- semantic translation succeeds
- canonical report artifact is successfully persisted

Phase 1 failure handling:
- event write failures should be degraded and observable
- they should not block final report delivery unless a later policy explicitly upgrades this to hard-fail

### Calibration integration

The new subdomain will build calibration observations for the existing Technical calibration domain.

Decision:
- do not move calibration ownership
- do not rewrite fitting logic in phase 1
- replace file-only observation sourcing with DB-backed observation building as the new mainline

### Market data access for labeling

The labeling worker should reuse the existing market-data provider contract, but with isolated runtime policy:
- separate cache namespace
- separate retry behavior
- separate rate-limit expectations
- point-in-time correctness rules

## Alternatives Considered

### A. Put registry and labeling inside `calibration`

Rejected.

Reason:
- calibration is a downstream consumer, not the owner of objective runtime truth capture
- this would invert the dependency direction

### B. Create cross-agent shared observability infrastructure now

Rejected for phase 1.

Reason:
- current repo architecture is agent-first
- premature shared infrastructure would increase coupling before a second consumer exists

### C. Store only derived boolean labels

Rejected.

Reason:
- destroys raw information needed for future reinterpretation and calibration design

### D. Use only views or materialized views for labels

Rejected as the only production answer.

Reason:
- views are useful for research and read models
- production labels still need a stable governed snapshot layer
- materialized views are a read optimization tool, not the source-of-truth answer

Supporting reference:
- [PostgreSQL REFRESH MATERIALIZED VIEW](https://www.postgresql.org/docs/current/sql-refreshmaterializedview.html)

### E. Drop DB foreign keys now for future partitioning freedom

Rejected for phase 1.

Reason:
- current scale does not justify giving up relational integrity
- this is premature optimization

### F. Use host cron to trigger Docker commands

Rejected for the supported deployment architecture.

Reason:
- it creates environment drift outside Compose-managed infrastructure
- it weakens observability and deployment reproducibility
- it adds an unnecessary compatibility branch

### G. Run an always-on Python scheduler loop in the API runtime

Rejected for phase 1.

Reason:
- it mixes scheduling responsibility into the online service
- it creates avoidable lifecycle and failure-mode coupling
- the use case only needs a simple container-native scheduler, not an in-process scheduling subsystem

## Consequences

### Positive consequences

- Technical decisions become traceable and falsifiable.
- Monitoring can begin before a full calibration program.
- Calibration gets a clean runtime-backed observation source.
- The design stays aligned with current repo boundaries.
- Docker deployments can support scheduled labeling without coupling it to the main online workflow.

### Negative consequences

- Semantic-translate success path adds an extra persistence step.
- New DB tables and migration surface increase operational complexity.
- Labeling quality depends on delayed market data availability and data quality.
- Partitioning and large-scale retention decisions are deliberately deferred, not solved forever.

## Rollout Plan

### Phase 1

- add `decision_observability` subdomain skeleton
- add `technical_prediction_events`
- write prediction events on technical finalization

### Phase 2

- add delayed labeling worker
- add `technical_outcome_paths`
- support daily cron-style execution and manual replay

### Phase 3

- add internal monitoring read models
- support internal SQL and notebook analysis

### Phase 4

- add approved production label snapshots
- add calibration observation builder integration

## Validation Gates

- changed-path lint and import hygiene
- ORM and repository tests
- event registration integration tests
- labeling idempotency tests
- point-in-time outcome resolution tests
- monitoring read-model query tests
- calibration observation compatibility tests

## Explicit Non-Goals

- no macro context work in this ADR
- no breadth platform in this ADR
- no new technical quant family in this ADR
- no phase-1 frontend dashboard commitment
- no phase-1 cross-agent observability platform
- no phase-1 forced partitioning or UUIDv7 migration

## Final Position

This ADR establishes an execution-ready consensus:
- code remains agent-local
- runtime truth is `events + raw outcomes`
- production labels are governed snapshots
- DB integrity is retained for now
- schema stays partition-ready without premature partition commitments
- Docker-based scheduled labeling is explicitly supported

This is the accepted architecture for the first enterprise-grade Technical decision observability backbone.
