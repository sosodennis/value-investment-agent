# Progress Log

## Session Start
- **Date**: 2026-03-17
- **Task**: 20260317-t27-regime-input-alignment
- **Goal**: Align regime compute with reusable deterministic feature and indicator inputs.

## Context Recovery Block
- **Current milestone**: Complete
- **Current status**: DONE
- **Current artifact**: `TODO.csv`
- **Key context**: This child intentionally comes last because it changes reusable deterministic surfaces and root orchestration. Projection and VP profile contracts should be stable first.
- **Next action**: Child task complete; bubble validation back to epic `SUBTASKS.csv` and close the epic.

## Slice 2 Complete: Canonical regime inputs in feature snapshots and indicator series
- **Completed**: 2026-03-17 23:28
- **Outcome**:
  - `FeatureRuntimeService` now emits canonical `ATR_14`, `ATRP_14`, `ADX_14`, and `BB_BANDWIDTH_20` snapshots for regime reuse.
  - `IndicatorSeriesRuntimeService` now emits matching deterministic series for chart/UI/diagnostics consumers.
  - The pandas-ta engine interface was aligned to the same canonical naming surface and no longer hard-codes `ATR_14` as unavailable when OHLC is present.

## Slice 3 Complete: Regime orchestration prefers canonical inputs with explicit fallback logging
- **Completed**: 2026-03-17 23:28
- **Outcome**:
  - `run_regime_compute_use_case` now loads feature and indicator artifacts before invoking the regime runtime.
  - Canonical deterministic inputs are projected into the regime path via typed per-timeframe metadata rather than hidden recomputation.
  - Missing canonical inputs now produce machine-readable degraded reasons such as `1d_REGIME_INPUT_ADX_14_TIMESERIES_COMPUTE` while keeping graceful fallback intact.

## Validation
- `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_regime_and_fusion.py finance-agent-core/tests/test_technical_application_use_cases.py -q` -> 23 passed
- `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_regime_and_fusion.py finance-agent-core/tests/test_technical_application_use_cases.py finance-agent-core/tests/test_artifact_contract_registry.py finance-agent-core/tests/test_workflow_state_contract_alignment.py -q` -> 33 passed
- `uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical/subdomains/features finance-agent-core/src/agents/technical/subdomains/regime finance-agent-core/src/agents/technical/application/use_cases/run_regime_compute_use_case.py finance-agent-core/tests/test_technical_regime_and_fusion.py finance-agent-core/tests/test_technical_application_use_cases.py` -> exit 0

## Compliance Notes
- Architecture-standard check found no new cross-layer leakage: cross-subdomain orchestration stayed in root `application`, deterministic policy stayed inside `features` and `regime`, and no compatibility shim was added.
- Hygiene sweep confirmed the new regime input metadata keys are present on both the producing and consuming sides.
