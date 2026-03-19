# Progress Log

## Session Start
- **Date**: 2026-03-19
- **Task name**: `20260319-t41-volatility-regime`
- **Task dir**: `.codex-tasks/20260319-technical-p1-quant-core-epic/tasks/20260319-t41-volatility-regime/`
- **Spec**: See `SPEC.md`
- **Plan**: See `TODO.csv`

## Context Recovery Block
- **Current milestone**: COMPLETE
- **Current status**: DONE
- **Current artifact**: `TODO.csv`
- **Next action**: Hand off to epic child #2 (`T42 liquidity proxy`).

## 2026-03-20 Execution Summary
- **Slice size**: medium
- **Boundary decision**:
  - keep the slice backend-only
  - land free-data-compatible volatility regime quant features inside the `features` owner path
  - avoid UI/readout changes until the later integration child
- **Implemented**:
  - added domain volatility helpers in `features/domain/volatility_service.py`
  - added three quant features in `FeatureRuntimeService`:
    - `VOL_REALIZED_20`
    - `VOL_DOWNSIDE_20`
    - `VOL_PERCENTILE_252`
  - attached deterministic provenance, warmup, and regime-state semantics
  - added runtime and application use-case regression coverage
- **Validation**:
  - `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_regime_and_fusion.py finance-agent-core/tests/test_technical_application_use_cases.py -q`
    - `38 passed`
  - `uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical/subdomains/features finance-agent-core/tests/test_technical_regime_and_fusion.py finance-agent-core/tests/test_technical_application_use_cases.py`
    - passed
  - `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_import_hygiene_guard.py finance-agent-core/tests/test_artifact_api_contract.py -q`
    - `9 passed`
- **Rollout notes**:
  - no frontend schema change in this child
  - no fusion math change in this child
  - new quant features remain additive and evidence-friendly for later integration
