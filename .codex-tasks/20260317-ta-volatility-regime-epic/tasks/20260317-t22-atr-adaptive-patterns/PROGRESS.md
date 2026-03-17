# Progress Log

## Session Start
- **Date**: 2026-03-17
- **Task**: 20260317-t22-atr-adaptive-patterns
- **Goal**: Land ATR/ATRP-scaled pattern thresholds with OHLC-aware runtime inputs.

## Context Recovery Block
- **Current milestone**: #2 — Wire OHLC-aware inputs into pattern runtime
- **Current status**: IN_PROGRESS
- **Current artifact**: `TODO.csv`
- **Key context**: Child task scaffolded under the TA volatility/regime epic. Next step is to pass OHLC series through the pattern compute path so volatility can be derived within the patterns subdomain.
- **Next action**: Update `run_pattern_compute_use_case.py` and pattern runtime to preserve OHLC series.

## Milestone 2-4 Completion Summary
- **Status**: DONE
- **Completed**: 2026-03-17 11:44
- **What was done**:
  - Wired `open/high/low/close` series from the timeseries bundle into the pattern compute path.
  - Replaced fixed pattern thresholds with ATR/ATRP-adaptive threshold derivation inside `pattern_detection_service.py`.
  - Exposed adaptive threshold diagnostics in `confidence_scores` for downstream inspection.
  - Added targeted pattern tests covering OHLC-aware ATR extraction, volatility expansion, and breakout buffering.
- **Validation**:
  - `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_patterns.py -q` -> exit 0
  - `uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical/subdomains/patterns finance-agent-core/src/agents/technical/application/use_cases/run_pattern_compute_use_case.py finance-agent-core/tests/test_technical_patterns.py` -> exit 0
  - `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_application_use_cases.py -q` -> exit 0
- **Next step**: Start T23 - regime subdomain and regime-aware fusion.
