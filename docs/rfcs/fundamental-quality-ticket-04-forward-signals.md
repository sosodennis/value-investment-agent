# Ticket 04: forward_signals Quality and Cohesion

## Requirement Breakdown
- Add explicit interface contracts to remove untyped `dict` propagation.
- Reduce fragmentation in `sec_xbrl` infrastructure by pipeline stage.
- Remove empty `application/` and `interface/` if contracts are not added.

## Technical Objectives and Strategy
- Define forward-signal schema and parser/serializer in `interface/`.
- Keep policies and calibration in `domain/` only.
- Re-package infrastructure pipeline into stage-specific subpackages.

## Involved Files
- `finance-agent-core/src/agents/fundamental/forward_signals/interface/*`
- `finance-agent-core/src/agents/fundamental/forward_signals/domain/*`
- `finance-agent-core/src/agents/fundamental/forward_signals/infrastructure/sec_xbrl/*`

## Slices

### Slice 1 (medium): Define Forward-Signal Interface Contracts
- Objective: add canonical models + parser/serializer for forward signals in `interface/`.
- Entry: confirm consumers (`workflow_orchestrator`, `core_valuation`) accept new shape.
- Exit: downstream uses typed contracts, minimal `dict[str, object]` at boundaries.
- Validation: `tests/test_sec_text_forward_signals.py`, `tests/test_sec_text_forward_signals_eval.py`.

### Slice 2 (medium): Re-package `sec_xbrl` by Pipeline Stage
- Objective: organize by `retrieval/`, `filtering/`, `matching/`, `postprocess/`.
- Entry: map modules to stages.
- Exit: imports updated; no stage cycles.
- Validation: `tests/test_sec_text_sentence_pipeline.py`, `tests/test_sec_text_model_loader_circuit_breaker.py`.

### Slice 3 (small): Remove Empty Layers (if any remain)
- Objective: remove empty `application/` or unused `interface/` if slice 1 is deferred.
- Entry: slice 1 decision complete.
- Exit: no empty layers left.
- Validation: `tests/test_fundamental_import_hygiene_guard.py`.

## Risk/Dependency Assessment
- Moderate risk from contract introduction; requires downstream changes.
- Pipeline repackage can cause import churn.

## Validation and Rollout Gates
- Lint: `ruff check` on touched files.
- Tests: `tests/test_sec_text_forward_signals*`, `tests/test_sec_text_sentence_pipeline.py`.

## Assumptions/Open Questions
- Confirm forward-signal schema is ready to standardize now (otherwise slice 1 is deferred).
