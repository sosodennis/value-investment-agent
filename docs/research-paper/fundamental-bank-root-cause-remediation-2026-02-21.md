# Fundamental Valuation Root-Cause Remediation Plan (2026-02-21)

## 1. Background

The current Fundamental valuation pipeline surfaced extreme Bank_DDM outputs (JPM case). Investigation showed two systemic root causes instead of a single bug:

1. **Output semantic mismatch**:
   - Bank_DDM Monte Carlo summary was treated as per-share in preview/UI, while the evaluator returned total equity value.
   - This made valid total values appear as absurd per-share prices.
2. **Insufficient bank input guardrails**:
   - Bank flow lacked strict per-share contract fields (`shares_outstanding`) and model-specific sanity checks.
   - When XBRL/mapping noise appears, engine still computes instead of failing closed with an explainable error.

## 2. Goals

1. Standardize valuation semantics across pipeline (total vs per-share is explicit).
2. Make Bank_DDM always produce both total equity value and per-share intrinsic value.
3. Ensure Monte Carlo distribution used by UI is explicitly per-share.
4. Add bank-specific fail-closed validation to prevent non-economic outputs from entering preview.
5. Preserve existing model behavior for SaaS/REIT/EVA while tightening contract clarity.

## 3. Scope

### In scope
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/engine/graphs/bank_ddm.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/skills/valuation_bank/schemas.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/skills/valuation_bank/tools.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/context.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/param_builder.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/application/fundamental_service.py`
- Related tests and fixtures.

### Out of scope (TODO / enhancement)
- HITL workflow integration.
- Industry-average fallback with mandatory manual approval gate.

## 4. Design

### 4.1 Unified valuation semantics contract

For Bank valuation results, backend must output:
- `equity_value` (total equity value)
- `intrinsic_value` (per-share)
- `shares_outstanding_used`
- distribution summary with explicit semantic tag:
  - `metric_type = intrinsic_value_per_share`

### 4.2 Bank parameter completeness

Bank param builder resolves `shares_outstanding` via existing market/XBRL precedence policy and passes it into `BankParams`.

### 4.3 Fail-closed bank validations

Before graph calculation:
- `shares_outstanding > 0`
- `0 < tier1_target_ratio <= 0.30`
- `0 < rwa_intensity <= 0.20`
- `initial_capital > 0`

If violated, return explicit error; do not produce valuation preview.

### 4.4 Preview distribution safety

`fundamental_service` only converts distribution summary to UI scenarios as per-share values.
- If `metric_type` indicates total equity, convert using `shares_outstanding` when available.
- If conversion is impossible, suppress distribution scenarios instead of showing misleading prices.

### 4.5 RWA continuity hardening

Bank param builder now performs additional continuity checks on latest `Risk-Weighted Assets` against historical median. If discontinuity is detected, it falls back to historical median RoRWA policy path.

## 5. Acceptance Criteria

1. Bank valuation API returns `intrinsic_value` and `equity_value` consistently.
2. Bank MC summary median represents per-share values.
3. Preview/UI no longer renders trillion-level per-share numbers caused by unit mismatch.
4. Invalid bank parameters fail with explicit errors.
5. Existing unit tests pass and new bank semantics tests are added.

## 6. Implementation Checklist

- [x] Update Bank graph to compute intrinsic per share.
- [x] Add `shares_outstanding` (and `current_price`) to BankParams.
- [x] Update bank param builder to populate shares and metadata source.
- [x] Add bank model input validations (fail-closed).
- [x] Change bank Monte Carlo evaluator to return per-share metric.
- [x] Add distribution `metric_type` for bank MC summary.
- [x] Harden preview distribution scenario mapping by metric semantics.
- [x] Add RWA discontinuity defense in bank param build flow.
- [x] Update/add tests and fixtures.
- [x] Run lint + targeted tests and record results.

## 7. Validation Results

### Lint
- Command:
  - `uv run --project finance-agent-core python -m ruff check ...`
- Result:
  - `All checks passed!`

### Tests
- Command:
  - `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_bank_reit_strategyized_models.py finance-agent-core/tests/test_fundamental_application_services.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_fundamental_backtest_runner.py -q`
- Result:
  - `26 passed, 2 warnings`

## 8. Change Log (Implemented)

1. **Bank graph**
   - Added intrinsic per-share node to Bank_DDM graph.
2. **Bank schema & tool**
   - Added `shares_outstanding` and `current_price` to `BankParams`.
   - Added fail-closed validation for bank critical inputs.
   - Bank valuation now returns `intrinsic_value`, `upside_potential`, `shares_outstanding_used`.
   - Bank Monte Carlo summary now tagged with `metric_type=intrinsic_value_per_share`.
3. **Builder layer**
   - Bank payload now resolves shares via market/XBRL policy and returns `shares_source`.
   - Added RWA discontinuity check and fallback path to historical median RoRWA.
4. **Preview safety**
   - Distribution scenario conversion now respects metric semantics and suppresses unsafe rendering when per-share conversion is impossible.
5. **Consistency**
   - Added `metric_type=intrinsic_value_per_share` in SaaS and REIT MC summaries.
6. **Tests/fixtures**
   - Updated bank tests and backtest fixtures for new required field and semantic behavior.

## 9. Remaining TODO / Enhancement

- HITL integration remains TODO.
- Industry-average fallback requiring manual approval remains TODO.
