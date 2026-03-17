# Progress Log

## Session Start
- **Date**: 2026-03-17
- **Task**: 20260317-t23-regime-aware-fusion
- **Goal**: Add a regime capability and condition technical fusion on market state.

## Context Recovery Block
- **Current milestone**: #4 — Run targeted validation and compliance sweep
- **Current status**: DONE
- **Current artifact**: `TODO.csv`
- **Key context**: The dedicated regime path is now in the workflow, and fusion consumes the saved regime artifact for regime-aware weighting and diagnostics.
- **Next action**: Hand off to T24.

## Milestone 2-4 Completion Summary
- **Status**: DONE
- **Completed**: 2026-03-17 22:22
- **What was done**:
  - Added a dedicated `regime_compute` node/use case, state field, repository port, and typed `ta_regime_pack` artifact contract.
  - Introduced regime-aware fusion scoring, risk floors, and scorecard/report diagnostics sourced from the saved regime pack.
  - Added focused regression tests for regime classification, fusion weighting, and application use-case wiring.
- **Validation**:
  - `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_regime_and_fusion.py finance-agent-core/tests/test_technical_application_use_cases.py -q` -> exit 0
  - `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_artifact_contract_registry.py finance-agent-core/tests/test_artifact_api_contract.py finance-agent-core/tests/test_workflow_state_contract_alignment.py -q` -> exit 0
  - `uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical/subdomains/regime finance-agent-core/src/agents/technical/subdomains/signal_fusion finance-agent-core/src/agents/technical/application/use_cases/run_regime_compute_use_case.py finance-agent-core/src/agents/technical/application/use_cases/run_fusion_compute_use_case.py finance-agent-core/src/interface/artifacts/artifact_contract_specs.py finance-agent-core/src/interface/artifacts/artifact_data_models.py` -> exit 0
- **Compliance**:
  - Added a lightweight `subdomains/regime/contracts.py` facade so cross-subdomain consumers avoid deep internal imports.
  - No blocking layer-boundary, migration-hygiene, or logging-rule violations were found in the changed T23 paths.
- **Next step**: Start T24 - VP-lite structure and confluence scoring.
