# Ticket 07: workflow_orchestrator Quality and Cohesion

## Requirement Breakdown
- Remove empty `domain/` and `infrastructure/` layers.
- Reduce fragmentation in `application/` by grouping flows, valuation services, and state owners.
- Ensure interface remains pure mapping/formatting (no domain policy).

## Technical Objectives and Strategy
- Re-package application into clear subfolders: `flows/`, `valuation/`, `state/`.
- Keep interface modules focused on serialization/preview formatting only.
- Align preview metrics dependency to `model_selection/interface` (decision).

## Involved Files
- `finance-agent-core/src/agents/fundamental/workflow_orchestrator/application/*`
- `finance-agent-core/src/agents/fundamental/workflow_orchestrator/interface/*`
- `finance-agent-core/src/agents/fundamental/workflow_orchestrator/domain/__init__.py`
- `finance-agent-core/src/agents/fundamental/workflow_orchestrator/infrastructure/__init__.py`

## Slices

### Slice 1 (small): Remove Empty Layers
- Objective: delete empty `domain/` and `infrastructure` packages.
- Entry: no imports depend on them.
- Exit: directories removed; hygiene guard updated.
- Validation: `tests/test_fundamental_import_hygiene_guard.py`.

### Slice 2 (medium): Re-package Application by Capability
- Objective: create `flows/`, `valuation/`, `state/` subpackages and move files.
- Entry: slice 1 complete.
- Exit: imports updated; no cycles; file roles are clear.
- Validation: `tests/test_fundamental_orchestrator_logging.py`, `tests/test_fundamental_application_services.py`.

### Slice 3 (small): Interface Purity Check
- Objective: ensure interface depends only on contracts/formatters and `model_selection/interface` for preview metrics.
- Entry: slice 2 complete.
- Exit: no interface → domain dependencies.
- Validation: `tests/test_fundamental_preview_layers.py`, `tests/test_fundamental_mapper.py`.

## Risk/Dependency Assessment
- Moderate risk due to many imports in application layer.

## Validation and Rollout Gates
- Lint: `ruff check` on touched files.
- Tests: orchestration and preview tests listed above.
