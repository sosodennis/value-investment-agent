# Fundamental FCFF-WACC and SBC Dilution Remediation Plan (2026-03-08)

## Requirement Breakdown
1. Objective
- Upgrade DCF (`dcf_growth`, `dcf_standard`) from CAPM-cost-of-equity proxy to true FCFF-WACC policy where data allows.
- Replace current SBC cash-flow handling from `+SBC addback` to conservative policy in this round: `no SBC addback` and denominator conservative preference (`diluted-priority` by conservative share count selection).
- Keep output as internal model valuation (not external target price passthrough), while improving enterprise-grade methodological correctness.

2. Success Criteria
- S1: DCF parameterization emits `wacc` from FCFF-WACC path (with explicit fallback reason when full inputs unavailable).
- S2: FCFF equation no longer adds SBC back; denominator policy prefers conservative shares path and is observable in assumptions/log metadata.
- NVDA/AAPL replay remains deterministic and contract-compatible, with no runtime regression and green targeted tests.

3. Constraints
- Direct rollout, no feature flag.
- Preserve current logging and assumption traceability style.
- Do not redesign DCF graph topology beyond required formula-policy correction.

4. Out of Scope (this round)
- No full option-overhang valuation (strike/maturity/volatility-based option liability).
- No provider expansion for option datasets.
- No frontend interaction redesign; only existing fields/logs/assumptions extension if needed.
- No changes to non-DCF models (bank/reit/residual-income/multiples) unless required for compile/test integrity.

## Technical Objectives and Strategy
1. S1 (FCFF-WACC correction)
- Build `wacc` as:
  - `ke = risk_free_rate + beta * market_risk_premium`
  - `wacc = ke * E/V + kd * (1-tax_rate) * D/V`
- Use market equity value (`current_price * shares_outstanding`) when available; otherwise deterministic fallback to existing CAPM-cost-of-equity path with explicit assumption.
- Use filing-derived debt cost when available (`interest_cost_rate`, with bounded clamp and clear fallback assumptions).

2. S2 (SBC + denominator conservative policy)
- Remove SBC addback from FCFF in DCF common math (`fcff = nopat + da - capex - delta_wc`).
- Add conservative denominator selection policy in SaaS/DCF parameterization:
  - prefer higher valid shares between resolved market shares and filing shares (conservative diluted-priority proxy),
  - emit assumption record with selected basis and reason.

3. S3 (design-only for next round)
- Option-overhang explicit adjustment design (inputs, artifact schema, policy, fallback).
- Not implemented in this execution.

## Involved Files
1. Core policy/formula
- `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/model_builders/saas/saas.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/engine/graphs/dcf_common.py`

2. Contracts / metadata / logs (if minimally required)
- `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/metadata_service.py` (only if new source token emitted)
- `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/model_builders/shared/value_extraction_common_service.py` (only if shares source token normalization needed)

3. Tests
- `finance-agent-core/tests/test_param_builder_canonical_reports.py`
- `finance-agent-core/tests/test_dcf_graph_tools.py`
- `finance-agent-core/tests/test_replay_fundamental_valuation_script.py` (regression guard if required)

## Detailed Per-File Plan
1. `saas.py`
- Add FCFF-WACC builder helper with typed input/output.
- Source inputs: `risk_free_rate`, `beta`, `market_risk_premium`, `tax_rate`, `total_debt`, `shares_outstanding`, `current_price`, `interest_cost_rate`.
- Add deterministic fallback branches with assumption text:
  - missing/invalid market equity value,
  - missing debt cost with positive debt,
  - non-positive capital weights.
- Add conservative shares denominator helper (select max valid shares across filing/resolved-market).

2. `dcf_common.py`
- Update `calculate_fcff(...)` to remove `+ sbc`.
- Keep signature stable in this round to minimize cross-file risk, but ignore `sbc_rates_converged` in computation.
- Preserve strict series-length checks for backward contract compatibility.

3. Tests
- Update WACC expectation tests to reflect FCFF-WACC path and fallback behavior.
- Add/adjust tests for:
  - FCFF no-SBC-addback behavior,
  - conservative shares denominator selection behavior/assumptions.

## Risk/Dependency Assessment
1. Functional risk
- Removing SBC addback can reduce intrinsic values materially for high-SBC names.
- Mitigation: targeted replay on NVDA/AAPL and regression checks.

2. Data risk
- Debt cost may be missing/noisy from filings.
- Mitigation: bounded clamp, explicit fallback assumptions, deterministic path.

3. Migration risk
- Existing tests may encode legacy CAPM-as-WACC expectations.
- Mitigation: update tests with explicit policy assertions instead of fragile numeric coupling where fallback path is expected.

4. Rollback
- Revert S1/S2 commits independently:
  - S1 rollback: restore CAPM-cost-of-equity `wacc` builder path.
  - S2 rollback: restore SBC addback and previous shares selection.

## Validation and Rollout Gates
1. Gate A (unit/contract)
- `ruff check` on changed files.
- `pytest` targeted:
  - `test_param_builder_canonical_reports.py`
  - `test_dcf_graph_tools.py`
  - any newly added targeted tests.

2. Gate B (replay/regression)
- Replay NVDA/AAPL baseline inputs and ensure:
  - no runtime error,
  - assumptions include new policy traces,
  - drift direction explainable by S1/S2 policy changes.

3. Gate C (compliance)
- No `Any` introduction.
- Keep layer boundaries unchanged (`domain/application/interface/infrastructure`).

## Assumptions/Open Questions
1. Confirmed: direct rollout without feature flag.
2. Confirmed: this round chooses `no SBC addback + conservative denominator` instead of full option-overhang valuation.
3. Open (next round/S3): option-overhang explicit valuation input contract and provider strategy.
