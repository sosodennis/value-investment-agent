# Progress Log

---

## Session Start

- **Date**: 2026-03-21 00:26
- **Task name**: `20260321-phase4-calibration`
- **Task dir**: `.codex-tasks/20260321-technical-decision-observability-epic/tasks/20260321-phase4-calibration/`
- **Spec**: See `SPEC.md`
- **Plan**: See `TODO.csv` (4 milestones)
- **Environment**: Python / pytest / ruff

---

## Context Recovery Block

- **Current milestone**: COMPLETE
- **Current status**: DONE
- **Last completed**: #4 — Add compatibility and regression coverage
- **Current artifact**: `.codex-tasks/20260321-technical-decision-observability-epic/tasks/20260321-phase4-calibration/TODO.csv`
- **Key context**: Calibration now consumes DB-backed observations through a decision-observability builder and runtime path, while offline file loading remains available for manual workflows.
- **Known issues**: Repo-wide `finance-agent-core/tests` still contains unrelated baseline failures outside this epic slice, so phase completion is based on focused changed-path gates.
- **Next action**: Epic complete unless a follow-up consumer or automation slice is approved.

---

## Milestone 1: Define builder contract and calibration facade boundary

- **Status**: DONE
- **Started**: 09:58
- **Completed**: 10:07
- **What was done**:
  - Added `TechnicalCalibrationObservationBuildResult` as the builder contract for calibration observation generation.
  - Added a decision-observability domain builder that produces the existing `TechnicalDirectionCalibrationObservation` contract.
  - Re-exported the builder through calibration domain and subdomain facades.
- **Key decisions**:
  - Decision: Keep the builder implementation in `decision_observability/domain` and only export it through calibration.
  - Reasoning: Calibration stays the downstream consumer, while observability retains ownership of the new truth-backed source.
  - Alternatives considered: Moving the builder into calibration was rejected because it would transfer observability knowledge into the wrong owner.
- **Problems encountered**:
  - Problem: The initial facade import path risked pulling the whole `decision_observability` package into calibration.
  - Resolution: Tightened the calibration domain import to `decision_observability.domain`.
  - Retry count: 1
- **Validation**: `uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical/subdomains/decision_observability finance-agent-core/src/agents/technical/subdomains/calibration finance-agent-core/tests/test_technical_decision_observability_calibration_builder.py finance-agent-core/tests/test_technical_import_hygiene_guard.py` -> exit 0
- **Files changed**:
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/domain/calibration_observation_builder_service.py` — added builder contract and builder implementation
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/domain/__init__.py` — exported builder contract and helper
  - `finance-agent-core/src/agents/technical/subdomains/calibration/domain/__init__.py` — exported the new builder through the calibration facade
  - `finance-agent-core/src/agents/technical/subdomains/calibration/__init__.py` — surfaced the builder from the subdomain root
- **Next step**: Milestone 2 — Implement observation builder from events plus outcomes

## Milestone 2: Implement observation builder from events plus outcomes

- **Status**: DONE
- **Started**: 09:58
- **Completed**: 10:07
- **What was done**:
  - Implemented builder logic that converts monitoring read-model rows into `TechnicalDirectionCalibrationObservation`.
  - Added drop-reason tracking for missing outcomes, missing raw scores, missing forward returns, and unsupported directions.
  - Added direction-family normalization that supports existing calibration aliases plus technical event prefixes.
- **Key decisions**:
  - Decision: Build from monitoring truth rows instead of directly from ORM models.
  - Reasoning: Phase 3 already established monitoring rows as the joined DB truth surface, so phase 4 should consume that stable contract.
  - Alternatives considered: Direct ORM/object coupling was rejected because it would bypass the new read-model seam and create deeper infrastructure dependencies.
- **Problems encountered**:
  - Problem: Existing calibration direction aliases did not fully cover technical event strings like `BEARISH_BREAKDOWN`.
  - Resolution: Added a builder-local fallback that maps `bullish_*` / `bearish_*` prefixes to calibration direction families.
  - Retry count: 0
- **Validation**: `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_decision_observability_calibration_builder.py finance-agent-core/tests/test_technical_decision_observability_monitoring.py finance-agent-core/tests/test_technical_decision_observability_worker.py finance-agent-core/tests/test_technical_decision_observability_labeling.py finance-agent-core/tests/test_technical_decision_observability_registry.py finance-agent-core/tests/test_technical_import_hygiene_guard.py -q` -> exit 0
- **Files changed**:
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/domain/calibration_observation_builder_service.py` — implemented builder semantics
- **Next step**: Milestone 3 — Wire calibration consumers while retaining offline file path

## Milestone 3: Wire calibration consumers while retaining offline file path

- **Status**: DONE
- **Started**: 09:58
- **Completed**: 10:07
- **What was done**:
  - Added runtime support for loading direction calibration observations from DB-backed monitoring rows.
  - Left `load_technical_direction_calibration_observations()` and the file-based calibration script unchanged.
  - Marked the DB-backed builder as the intended mainline source for future integrated consumers.
- **Key decisions**:
  - Decision: Wire the mainline source through `TechnicalDecisionObservabilityRuntimeService` instead of rewriting the existing offline calibration script.
  - Reasoning: The script remains a manual/offline utility, while the runtime path becomes the clean source for future integrated consumers.
  - Alternatives considered: Replacing the file-based script flow outright was rejected because the task explicitly keeps that path available.
- **Problems encountered**:
  - Problem: None after the builder contract was in place.
  - Resolution: N/A
  - Retry count: 0
- **Validation**: `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_decision_observability_calibration_builder.py -q` -> exit 0
- **Files changed**:
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/application/decision_observability_runtime_service.py` — added calibration observation runtime loader
- **Next step**: Milestone 4 — Add compatibility and regression coverage

## Milestone 4: Add compatibility and regression coverage

- **Status**: DONE
- **Started**: 09:58
- **Completed**: 10:07
- **What was done**:
  - Added focused regression tests for builder output, drop reasons, runtime integration, and calibration facade exports.
  - Re-ran the monitoring / labeling / registry / hygiene suite alongside the new calibration builder tests.
- **Key decisions**:
  - Decision: Use focused compatibility coverage against the existing contracts instead of expanding into repo-wide regression scope.
  - Reasoning: This keeps the slice auditable and avoids conflating unrelated baseline failures with the phase-4 integration work.
  - Alternatives considered: Repo-wide pytest was not used as the completion gate because it remains baseline-red outside this epic slice.
- **Problems encountered**:
  - Problem: Only import-order formatting remained after the runtime and builder tests passed.
  - Resolution: Applied a narrow `ruff --fix` pass on the affected changed files.
  - Retry count: 1
- **Validation**: `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_decision_observability_calibration_builder.py finance-agent-core/tests/test_technical_decision_observability_monitoring.py finance-agent-core/tests/test_technical_decision_observability_worker.py finance-agent-core/tests/test_technical_decision_observability_labeling.py finance-agent-core/tests/test_technical_decision_observability_registry.py finance-agent-core/tests/test_technical_import_hygiene_guard.py -q` -> exit 0; `uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical/subdomains/decision_observability finance-agent-core/src/agents/technical/subdomains/calibration finance-agent-core/tests/test_technical_decision_observability_calibration_builder.py finance-agent-core/tests/test_technical_import_hygiene_guard.py` -> exit 0
- **Files changed**:
  - `finance-agent-core/tests/test_technical_decision_observability_calibration_builder.py` — added phase-4 calibration builder tests
- **Next step**: Phase 4 complete

---

## Final Summary

- **Total milestones**: 4
- **Completed**: 4
- **Failed + recovered**: 2
- **External unblock events**: 0
- **Total retries**: 2
- **Files created**: 4
- **Files modified**: 5
- **Key learnings**:
  - Calibration integration works cleanly when the builder consumes monitoring truth rows rather than ORM models or file payloads.
- **Recommendations for future tasks**:
  - If a future recalibration pipeline is added, point it at the runtime builder path first and treat file export as an optional offline utility.
