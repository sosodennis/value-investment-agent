# Refactor Workstreams Progress (Current)
Date: 2026-02-13
Status: Active working tracker
Scope: `finance-agent-core`

This document tracks the two active refactor workstreams and defines execution order.

## 1. Workstream A: Artifact Port Simplification

Goal:
1. Reduce data-layer boilerplate by converging on shared generic `TypedArtifactPort`.
2. Keep strict contract validation and zero-compat behavior unchanged.

Current status: `COMPLETED`

Phase 4 completion:
1. Unified artifact kind->model routing in `src/interface/artifacts/artifact_contract_registry.py`.
2. Removed debate/news/technical special parsing helpers from registry usage path.
3. `debate/data/report_reader.py` now uses generic registry parse APIs.
4. Enhanced `src/shared/cross_agent/data/typed_artifact_port.py`:
   - `load(artifact_id: object, ...)` with built-in id guard
   - `load_json(...)` unified model dump
5. Updated per-agent data ports to consume unified behavior:
   - `src/agents/fundamental/data/ports.py`
   - `src/agents/news/data/ports.py`
   - `src/agents/technical/data/ports.py`
   - `src/agents/debate/data/ports.py`

Validation evidence:
1. `ruff` checks on touched files: passed
2. Targeted + core tests: passed

Remaining:
1. None (closed for this workstream scope).

Closure notes:
1. Consolidated repetitive forwarding implementation in `src/agents/news/data/ports.py` with internal generic helpers (`_save_port`, `_load_port`, `_dump_models`).
2. Final policy documented in `docs/backend-guideline.md` (Typed Artifact Port Policy section).
3. Decision: keep thin per-agent facades when they provide domain naming/composition clarity; eliminate meaningless pass-through duplication.

## 2. Workstream B: Pydantic Contract Boilerplate Reduction

Goal:
1. Reduce repetitive Pydantic validators.
2. Preserve strict fail-fast and domain semantic normalization rules.

Current status: `COMPLETED`

Completed:
1. Proposal aligned to current architecture/policy:
   - `docs/pydantic_refactoring_proposal.md`
2. Phase 1 (technical interface contracts) started and completed:
   - Added local technical annotated primitive aliases in:
     - `finance-agent-core/src/agents/technical/interface/types.py`
   - Refactored `technical/interface/contracts.py` to use typed aliases and removed repetitive field validators.
   - Parsing behavior kept strict fail-fast; no compatibility branch introduced.
   - Validation suites passed (technical + serializer/artifact + core regression sets).
3. Phase 2 (news interface contracts) completed:
   - Added local news annotated primitive aliases in:
     - `finance-agent-core/src/agents/news/interface/types.py`
   - Refactored `news/interface/contracts.py` to use typed aliases and removed repetitive field validators.
   - Parsing behavior kept strict fail-fast; no compatibility branch introduced.
   - Validation suites passed (news + serializer/artifact + core regression sets).
4. Phase 3 (debate interface contracts) completed:
   - Added local debate annotated primitive aliases in:
     - `finance-agent-core/src/agents/debate/interface/types.py`
   - Refactored `debate/interface/contracts.py` to use typed aliases and removed repetitive field validators.
   - Preserved debate-specific semantic checks (`evidence.value`, `evidence.provenance`, `data_quality_warning`) as explicit validators.
   - Parsing behavior kept strict fail-fast; no compatibility branch introduced.
   - Validation suites passed (debate + serializer/artifact + core regression sets).

Completed:
1. Phase 4 Slice A (low-risk):
   - Added local fundamental annotated text alias:
     - `finance-agent-core/src/agents/fundamental/interface/types.py`
   - Refactored `FundamentalArtifactModel` text field validator to typed alias usage:
     - `finance-agent-core/src/agents/fundamental/interface/contracts.py`
   - Preserved all high-risk semantic validators/model validators unchanged.
   - Validation suites passed (fundamental + serializer/artifact + core regression sets).
2. Phase 4 Slice B (traceable primitives):
   - Extended `fundamental/interface/types.py` with annotated traceable aliases:
     - `TraceableValue`
     - `TraceableProvenance`
     - `TraceableOptionalText`
   - Refactored `TraceableFieldModel` in `fundamental/interface/contracts.py` to consume these aliases.
   - Preserved high-risk semantic validators/model validators (`_coerce_scalar`, report normalization/inference) unchanged.
   - Validation suites passed (fundamental + serializer/artifact + core regression sets).
3. Phase 4 Slice C (shared list validation helper):
   - Added `validate_list_and_dump(...)` in:
     - `finance-agent-core/src/interface/artifacts/artifact_model_shared.py`
   - Replaced `parse_financial_reports_model(...)` manual loop in:
     - `finance-agent-core/src/agents/fundamental/interface/contracts.py`
   - Parsing behavior remains strict fail-fast; no semantic changes.
4. Fundamental test-path alignment fix:
   - Updated outdated mock target in:
     - `finance-agent-core/tests/test_error_handling_fundamental.py`
   - `test_model_selection_node_accepts_canonical_report_shape` now mocks `load_financial_reports` (current orchestrator path), preventing DB dependency in unit test.

Guardrails:
1. `Annotated + BeforeValidator` only for primitive/format normalization.
2. Business semantic validators remain explicit (especially fundamental report semantics).
3. No compatibility fallback behavior introduced.

## 3. Execution Order (Decision)

Recommended order:
1. Both workstreams are complete in current scope; start a new tracker only if expanding scope.

Reason:
1. Workstream A data-port convergence is closed.
2. Workstream B phases 1-4 are closed with stable regression results.

## 4. Definition of Done

Workstream A done:
1. Per-agent data ports keep meaningful domain-level helpers; repetitive pass-through bodies are consolidated.
2. `TypedArtifactPort` is the default data contract path.
3. Backend guideline includes final Typed Artifact Port policy.

Workstream B done when:
1. Validator boilerplate reduced across target agents.
2. All existing contract behavior remains stable (tests unchanged in semantics).
3. No domain semantic logic moved into generic alias abstractions.

Current completion:
1. Done (all criteria satisfied in current scope).

## 5. Follow-up Slice: Interface Simplification (Completed)

Goal:
1. Remove global thin facade `src/interface/canonical_serializers.py`.
2. Make agent-local interface contracts the only canonicalization entrypoints.

Completed:
1. Replaced global facade usage with agent-local parsers:
   - fundamental: `parse_financial_reports_model`, `parse_fundamental_artifact_model`
   - news: `parse_news_artifact_model`
   - technical: `parse_technical_artifact_model`
   - debate: `parse_debate_artifact_model` (new helper added)
2. Updated workflow/data call sites and tests.
3. Removed file:
   - `finance-agent-core/src/interface/canonical_serializers.py`
4. Updated active docs to reflect parser-first path.
5. Consolidated artifact contract mapping into SSOT:
   - Added `finance-agent-core/src/interface/artifacts/artifact_contract_specs.py`
   - `artifact_contract_registry.py` and `artifact_api_models.py` now share the same `kind -> model` specs.

Validation evidence:
1. `ruff` checks on touched files: passed.
2. Targeted suites: passed.
3. Core regression (`protocol/mappers/news_mapper/debate_mapper`): passed.

## 6. Follow-up Slice: Interface Package Split (Completed)

Goal:
1. Split `src/interface` into clear sub-packages:
   - `src/interface/artifacts/*`
   - `src/interface/events/*`
2. Eliminate flat mixed-responsibility interface module layout.

Completed:
1. Moved artifact-facing modules to:
   - `finance-agent-core/src/interface/artifacts/`
2. Moved event/protocol-facing modules to:
   - `finance-agent-core/src/interface/events/`
3. Updated all runtime imports (`src/`, `api/`, `tests`) to new paths.
4. Updated active docs to new path map.

Validation evidence:
1. `ruff` checks on touched files: passed.
2. Regression suites:
   - `test_protocol/test_mappers/test_news_mapper/test_debate_mapper`
   - `test_artifact_contract_registry/test_artifact_api_contract/test_output_contract_serializers/test_protocol_fixtures`
   All passed.
