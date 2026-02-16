# Agent Horizontal Consistency Checklist (Post-X3)

Date: 2026-02-13
Scope: `finance-agent-core/src/agents/{intent,fundamental,news,technical,debate}`
Baseline: `docs/clean-architecture-engineering-guideline.md`, `docs/backend-guideline.md`
Policy: Zero compatibility, contract-first, fail-fast.

## 1. Purpose

This checklist captures **remaining non-X3 horizontal boundary risks** after X3 completion.

Definition:
1. Not covered by X3 ("domain JSON payload dependency").
2. Impacts cross-agent maintainability, placement ambiguity, or layer ownership.
3. Should be resolved before starting new large feature tracks.

## 2. Quick Status

| Area | Status | Notes |
|---|---|---|
| Cross-agent internal imports (`agent A` importing `agent B` internals) | PASS | No new direct internal coupling found in scanned agent packages. |
| Domain importing data/interface layers | PASS | Core domain packages are clean for this rule in scanned files. |
| Legacy compatibility fallback in workflow contract path | PASS | No new compatibility fallback branch in the audited path. |
| Application layer ownership consistency | PASS | H2 Slice A/B completed for intent/fundamental/news/technical. |
| Naming/placement consistency | PASS | H4 naming cleanup completed for resilience vs compatibility semantics. |

## 3. Remaining Findings

## H1 (P1) Debate application directly reads data adapter implementation

- Files:
  - `finance-agent-core/src/agents/debate/application/use_cases.py`
  - `finance-agent-core/src/agents/debate/application/report_service.py`
- Symptom:
  - Application layer imports `debate/data/report_reader.py` implementation directly.
- Why this matters:
  - Application becomes tied to concrete data implementation, increasing refactor cost.
- Target state:
  1. Introduce application port for debate source loading.
  2. Inject data implementation from orchestration/bootstrap.
  3. `application/*` imports ports only, not data module implementation.
- Status: DONE (2026-02-13)
- Completion:
  1. Added `DebateSourceReaderPort` (`debate/application/ports.py`).
  2. Moved `DebateSourceData` to application DTO (`debate/application/dto.py`).
  3. `debate/application/{use_cases,report_service}.py` now consume injected source reader port.
  4. Concrete data implementation now lives in `debate/data/report_reader.py` (`debate_source_reader`) and is injected from `workflow/nodes/debate/nodes.py`.

## H2 (P1) Application layer still contains interface/data coupling hotspots

- Representative files:
  - `finance-agent-core/src/agents/fundamental/application/orchestrator.py`
  - `finance-agent-core/src/agents/fundamental/application/use_cases.py`
  - `finance-agent-core/src/agents/news/application/orchestrator.py`
  - `finance-agent-core/src/agents/technical/application/orchestrator.py`
  - `finance-agent-core/src/agents/intent/application/orchestrator.py`
- Symptom:
  - Application orchestrators/use-cases import interface mappers/serializers and some concrete data helpers.
- Why this matters:
  - Placement decision remains ambiguous for contributors ("put logic in app or interface?").
- Target state:
  1. Keep application focused on use-case flow and domain decisions.
  2. Move interface formatting/serialization calls to explicit adapter boundaries.
  3. Keep data conversion in data layer (or injected ports), not in app orchestration.
- Status: DONE (Slice A + Slice B done, 2026-02-13)
- Completion (Slice A):
  1. Removed application-level singleton concrete bindings for `intent/news/technical/fundamental`.
  2. Moved orchestrator concrete wiring to workflow node boundaries:
     - `workflow/nodes/intent_extraction/nodes.py`
     - `workflow/nodes/financial_news_research/nodes.py`
     - `workflow/nodes/technical_analysis/nodes.py`
     - `workflow/nodes/fundamental_analysis/nodes.py`
  3. Application modules now expose orchestrator classes without embedding concrete data/interface implementation instances.
- Completion (Slice B - intent/fundamental/news/technical):
  1. Removed app-layer `interface` imports from:
     - `finance-agent-core/src/agents/intent/application/{use_cases,orchestrator}.py`
     - `finance-agent-core/src/agents/fundamental/application/{use_cases,orchestrator,ports}.py`
     - `finance-agent-core/src/agents/news/application/{orchestrator,analysis_service,selection_service}.py`
     - `finance-agent-core/src/agents/technical/application/{orchestrator,report_service,semantic_service}.py`
  2. Moved news parser/formatter logic into application boundary:
     - `finance-agent-core/src/agents/news/application/parsers.py`
     - `finance-agent-core/src/agents/news/application/prompt_formatters.py`
  3. Converted intent/fundamental/news/technical application modules to injected adapter callables from workflow boundaries.
  4. Replaced app-layer artifact builder coupling (`src.interface.events.schemas`) with workflow-injected builders in intent/news/technical/fundamental paths.
- Remaining:
  1. None for H2 scope.

## H3 (P2) Technical domain serialization model still uses generic dict objects

- File:
  - `finance-agent-core/src/agents/technical/domain/models.py`
- Symptom:
  - `FracdiffSerializationResult` keeps fields as `dict[str, object]` (`bollinger/stat_strength/obv`).
- Why this matters:
  - Weak contracts inside domain reduce IDE/type safety and allow schema drift.
- Target state:
  1. Replace those fields with typed value objects.
  2. Keep raw JSON shaping strictly in data/interface serialization boundary.
- Status: DONE (2026-02-13)
- Completion:
  1. Added typed value objects in technical domain:
     - `BollingerSnapshot`
     - `StatisticalStrengthSnapshot`
     - `ObvSnapshot`
  2. Updated `FracdiffSerializationResult` to use typed fields instead of `dict[str, object]`.
  3. Updated technical data/application consumers to convert snapshots via `to_dict()` only at boundary output points.
  4. Updated tests to assert typed fields (`result.bollinger.state`, etc.).

## H4 (P2) "fallback" naming overlaps business resilience and compatibility semantics

- Representative files:
  - `finance-agent-core/src/agents/news/application/selection_service.py`
  - `finance-agent-core/src/agents/news/application/analysis_service.py`
  - `finance-agent-core/src/agents/intent/application/use_cases.py`
  - `finance-agent-core/src/agents/debate/application/state_readers.py` (docstring wording)
- Symptom:
  - `fallback` is used for both intended business degradation and legacy compatibility concerns.
- Why this matters:
  - Reviewers may misclassify acceptable resilience logic as forbidden compatibility logic.
- Target state:
  1. Keep resilience paths, but rename/document as `degraded_path` / `resilience_policy`.
  2. Reserve "compatibility" term exclusively for legacy-shape support (forbidden by policy).
- Status: DONE (2026-02-13)
- Completion:
  1. Renamed news application fallback helpers to resilience/degraded naming:
     - `run_selector_with_resilience`
     - `build_selector_degraded_indices`
     - `run_analysis_with_resilience`
  2. Updated intent extraction wording from "fallback" to "heuristic resilience path".
  3. Updated debate state reader docstring wording to resilience semantics.
  4. Updated tests and call sites accordingly.

## 4. Suggested Execution Order

1. H1 (P1): Debate application port split (highest ROI for clean boundary confidence).
2. H2 (P1): Standardize app/interface/data boundary call pattern agent-by-agent.
3. All identified post-X3 horizontal items (H1-H4) completed.

## 5. Definition of Done (for each item)

1. No direct implementation import across forbidden layer boundary.
2. Added/updated tests for moved responsibility.
3. `ruff` and targeted `pytest` green.
4. No compatibility branch introduced.
5. Documentation updated when ownership changes.

## 6. What is already solid (do not regress)

1. X3 outcome: domain JSON-path dependency has been removed in targeted paths.
2. Artifact contract path is envelope + kind/version guarded.
3. Cross-agent payload consumption follows shared contract route (no direct producer internals).
