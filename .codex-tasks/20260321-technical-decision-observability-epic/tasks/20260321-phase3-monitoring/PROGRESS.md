# Progress Log

---

## Session Start

- **Date**: 2026-03-21 00:26
- **Task name**: `20260321-phase3-monitoring`
- **Task dir**: `.codex-tasks/20260321-technical-decision-observability-epic/tasks/20260321-phase3-monitoring/`
- **Spec**: See `SPEC.md`
- **Plan**: See `TODO.csv` (4 milestones)
- **Environment**: Python / SQLAlchemy / pytest / ruff

---

## Context Recovery Block

- **Current milestone**: COMPLETE
- **Current status**: DONE
- **Last completed**: #4 — Add aggregation correctness and contract tests
- **Current artifact**: `.codex-tasks/20260321-technical-decision-observability-epic/tasks/20260321-phase3-monitoring/TODO.csv`
- **Key context**: Monitoring now reads joined DB truth from prediction events and outcome paths, with domain-owned aggregate semantics and internal DTO helpers for rows and aggregates.
- **Known issues**: Repo-wide `finance-agent-core/tests` still contains unrelated baseline failures outside this epic slice, so phase completion is based on focused changed-path gates.
- **Next action**: Hand off to child task #4 for calibration observation builder integration.

---

## Milestone 1: Define monitoring query scope and aggregation contract

- **Status**: DONE
- **Started**: 09:06
- **Completed**: 09:13
- **What was done**:
  - Added `MonitoringQueryScope`, `TechnicalMonitoringReadModelRow`, and `TechnicalMonitoringAggregate` to the decision-observability domain contracts.
  - Added `build_monitoring_query_scope()` to normalize filters and clamp limits.
  - Added `compute_monitoring_aggregates()` to fix the phase-1 aggregate semantics around `timeframe`, `horizon`, and `logic_version`.
- **Key decisions**:
  - Decision: Keep aggregate semantics in the domain layer instead of hard-coding them into SQL.
  - Reasoning: This preserves a single semantic owner for monitoring rollups while still using DB truth as the read source.
  - Alternatives considered: Pure SQL `GROUP BY` aggregation was rejected for phase 1 because it would make aggregate semantics harder to evolve safely.
- **Problems encountered**:
  - Problem: The first accumulator draft used mutable dataclass defaults.
  - Resolution: Switched those metric trackers to `default_factory`.
  - Retry count: 1
- **Validation**: `uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical/subdomains/decision_observability finance-agent-core/tests/test_technical_decision_observability_monitoring.py finance-agent-core/tests/test_technical_import_hygiene_guard.py` -> exit 0
- **Files changed**:
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/domain/contracts.py` — added monitoring contracts
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/domain/monitoring_read_model_service.py` — added scope normalization and aggregate semantics
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/domain/__init__.py` — exported monitoring contracts and helpers
- **Next step**: Milestone 2 — Implement monitoring read-model service and repository queries

## Milestone 2: Implement monitoring read-model service and repository queries

- **Status**: DONE
- **Started**: 09:06
- **Completed**: 09:13
- **What was done**:
  - Extended the application repository port with `fetch_monitoring_rows(scope=...)`.
  - Added repository left-join reads over `technical_prediction_events` and `technical_outcome_paths`.
  - Added runtime methods to load monitoring rows and aggregates from DB-backed truth.
- **Key decisions**:
  - Decision: Use a left join keyed by `labeling_method_version` so unresolved events remain visible in monitoring.
  - Reasoning: Monitoring needs both labeled and unresolved counts; an inner join would hide backlog coverage.
  - Alternatives considered: Querying only resolved outcome rows was rejected because it would lose unresolved coverage status.
- **Problems encountered**:
  - Problem: None beyond the accumulator initialization issue already fixed in milestone 1.
  - Resolution: N/A
  - Retry count: 0
- **Validation**: `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_decision_observability_monitoring.py finance-agent-core/tests/test_technical_decision_observability_worker.py finance-agent-core/tests/test_technical_decision_observability_labeling.py finance-agent-core/tests/test_technical_decision_observability_registry.py finance-agent-core/tests/test_technical_import_hygiene_guard.py -q` -> exit 0
- **Files changed**:
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/application/ports.py` — added monitoring read method to the repository port
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/application/decision_observability_runtime_service.py` — added monitoring row and aggregate loaders
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/infrastructure/repository.py` — added monitoring row query and mapping
- **Next step**: Milestone 3 — Add interface DTOs and internal consumer integration points

## Milestone 3: Add interface DTOs and internal consumer integration points

- **Status**: DONE
- **Started**: 09:06
- **Completed**: 09:13
- **What was done**:
  - Added interface DTOs for monitoring rows and aggregates.
  - Added conversion helpers and exported them through the subdomain facade.
  - Kept the consumer surface internal-only and avoided adding a dashboard or public API layer.
- **Key decisions**:
  - Decision: Put monitoring DTOs under `decision_observability/interface` rather than the top-level technical interface package.
  - Reasoning: The capability remains agent-local and should not leak as a cross-agent interface surface in phase 1.
  - Alternatives considered: Reusing the top-level technical interface package was rejected because it would blur subdomain ownership.
- **Problems encountered**:
  - Problem: None.
  - Resolution: N/A
  - Retry count: 0
- **Validation**: `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_decision_observability_monitoring.py -q` -> exit 0
- **Files changed**:
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/interface/contracts.py` — added DTOs and conversion helpers
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/interface/__init__.py` — exported interface helpers
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/__init__.py` — surfaced interface exports
- **Next step**: Milestone 4 — Add aggregation correctness and contract tests

## Milestone 4: Add aggregation correctness and contract tests

- **Status**: DONE
- **Started**: 09:06
- **Completed**: 09:13
- **What was done**:
  - Added focused tests for scope normalization, aggregate grouping, repository row mapping, runtime aggregate loading, and DTO conversion.
  - Kept validation tied to changed paths plus the existing import hygiene guard.
- **Key decisions**:
  - Decision: Use focused tests as the phase completion gate instead of repo-wide pytest.
  - Reasoning: Repo-wide pytest is still baseline-red outside this epic slice, and phase completion should stay evidence-based rather than blocked by unrelated failures.
  - Alternatives considered: Waiting for a full-suite green repo was rejected as out of scope for this child task.
- **Problems encountered**:
  - Problem: None after the accumulator fix.
  - Resolution: N/A
  - Retry count: 0
- **Validation**: `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_decision_observability_monitoring.py finance-agent-core/tests/test_technical_decision_observability_worker.py finance-agent-core/tests/test_technical_decision_observability_labeling.py finance-agent-core/tests/test_technical_decision_observability_registry.py finance-agent-core/tests/test_technical_import_hygiene_guard.py -q` -> exit 0; `uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical/subdomains/decision_observability finance-agent-core/tests/test_technical_decision_observability_monitoring.py finance-agent-core/tests/test_technical_import_hygiene_guard.py` -> exit 0
- **Files changed**:
  - `finance-agent-core/tests/test_technical_decision_observability_monitoring.py` — added monitoring-focused tests
- **Next step**: Phase 3 complete

---

## Final Summary

- **Total milestones**: 4
- **Completed**: 4
- **Failed + recovered**: 1
- **External unblock events**: 0
- **Total retries**: 1
- **Files created**: 4
- **Files modified**: 9
- **Key learnings**:
  - Monitoring stays easier to evolve when DB joins provide truth rows and the domain layer owns aggregate semantics.
- **Recommendations for future tasks**:
  - Keep phase-4 calibration integration consuming these read-model contracts without moving monitoring ownership out of decision observability.
