# Ticket 02: core_valuation Quality and Cohesion

## Requirement Breakdown
- Reduce fragmentation in `domain/` (especially `parameterization/model_builders/shared`).
- Remove empty layers (`application/`, `infrastructure`).
- Preserve heavy-compute boundaries and performance gates.

## Technical Objectives and Strategy
- Keep deterministic valuation logic in `domain/` only.
- Replace generic “common/shared” file names with explicit owners or consolidated modules.
- Maintain Monte Carlo and performance gates unchanged unless explicitly improved.

## Involved Files
- `finance-agent-core/src/agents/fundamental/core_valuation/application/__init__.py`
- `finance-agent-core/src/agents/fundamental/core_valuation/infrastructure/__init__.py`
- `finance-agent-core/src/agents/fundamental/core_valuation/domain/parameterization/model_builders/shared/*`
- `finance-agent-core/src/agents/fundamental/core_valuation/domain/engine/monte_carlo*.py`
- `finance-agent-core/src/agents/fundamental/core_valuation/interface/replay_contracts.py`

## Slices

### Slice 1 (small): Remove Empty Layers
- Objective: delete empty `application/` and `infrastructure` packages.
- Entry: no imports depend on these packages.
- Exit: directories removed; import hygiene guard updated if needed.
- Validation: `ruff check` on touched paths; `tests/test_fundamental_import_hygiene_guard.py`.

### Slice 2 (medium): Consolidate “shared/common” Owners
- Objective: remove generic `*common*` file names and consolidate into clear owner modules.
- Candidates: `common_output_assembly_service.py`, `value_extraction_common_service.py`.
- Entry: identify primary consumer modules and confirm single-owner responsibility.
- Exit: no `common`/`shared` file names remain unless required by cross-model policies.
- Validation: `tests/test_param_builder_canonical_reports.py`, `tests/test_saas_missing_input_policy.py`.

### Slice 3 (small): Replay Contract Placement Audit
- Objective: confirm `interface/replay_contracts.py` is the correct owner (and not a cross-subdomain shared artifact).
- Entry: slice 2 complete.
- Exit: either keep as-is with justification or relocate to an explicit shared replay package.
- Validation: `tests/test_build_fundamental_replay_manifest_script.py` and replay scripts smoke check (if required).

### Slice 4 (small): Performance Gate Checkpoint
- Objective: ensure any refactor does not regress Monte Carlo performance gate.
- Entry: slices 1–3 complete.
- Exit: performance gate test unchanged and green.
- Validation: `tests/test_fundamental_monte_carlo_performance_gate.py`.

## Risk/Dependency Assessment
- Moderate risk if consolidation touches parameterization builders.
- Performance gates are sensitive; keep changes localized.

## Validation and Rollout Gates
- Lint: `ruff check` on touched files.
- Tests: param builder tests + Monte Carlo gate.

## Assumptions/Open Questions
- No new application-layer use-cases are planned for core valuation in the immediate cycle.
