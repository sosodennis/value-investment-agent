# Ticket 06: model_selection Quality and Cohesion

## Requirement Breakdown
- Remove empty `application/` and `infrastructure` layers.
- Remove cross-layer dependency from `workflow_orchestrator/interface` to `model_selection/domain`.
- Reduce domain fragmentation if multiple single-use services exist.

## Technical Objectives and Strategy
- Keep domain cohesive and focused on selection logic and scoring.
- Move preview-metrics extraction into `model_selection/interface` (decision) to avoid interface → domain leakage.

## Involved Files
- `finance-agent-core/src/agents/fundamental/model_selection/domain/*`
- `finance-agent-core/src/agents/fundamental/model_selection/interface/report_projection_service.py`
- `finance-agent-core/src/agents/fundamental/workflow_orchestrator/interface/preview_projection_service.py`
- `finance-agent-core/src/agents/fundamental/model_selection/application/__init__.py`
- `finance-agent-core/src/agents/fundamental/model_selection/infrastructure/__init__.py`

## Slices

### Slice 1 (small): Remove Empty Layers
- Objective: delete `application/` and `infrastructure` packages.
- Entry: no imports depend on them.
- Exit: directories removed; hygiene guard updated.
- Validation: `tests/test_fundamental_import_hygiene_guard.py`.

### Slice 2 (medium): Move Preview Metrics to Interface (Chosen Direction)
- Objective: relocate `extract_latest_preview_metrics` (or equivalent) into `model_selection/interface` and update consumers.
- Entry: slice 1 complete.
- Exit: `workflow_orchestrator/interface` depends only on `model_selection/interface` for preview metrics.
- Validation: `tests/test_fundamental_preview_layers.py`, `tests/test_fundamental_mapper.py`.

### Slice 3 (small): Domain Cohesion Pass
- Objective: collapse ultra-small domain services if always used together, or create subpackage grouping.
- Entry: slice 2 complete.
- Exit: domain files map to clear responsibilities (no single-use wrappers).
- Validation: `tests/test_fundamental_model_selection_projection.py`, `tests/test_fundamental_model_type_mapping.py`.

## Risk/Dependency Assessment
- Moderate risk due to preview output changes.

## Validation and Rollout Gates
- Lint: `ruff check` on touched files.
- Tests: preview-related tests and model selection projection tests.
