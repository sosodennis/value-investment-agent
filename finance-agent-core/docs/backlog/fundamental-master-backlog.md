# Fundamental Master Backlog
Last Reviewed: 2026-03-09
Owner: Fundamental Maintainer
Cadence: Bi-weekly (artifact output, manual paste)

## Scope
- Consolidate all fundamental backlog/planning docs into one execution entrypoint.
- Keep old docs for traceability; execution priority is managed only here.

## Status Legend
- `Now`: currently executing
- `Next`: ready to execute next
- `Later`: planned but not scheduled
- `Blocked`: waiting on dependency/decision
- `Done`: implemented and verified
- `Superseded`: replaced by newer plan and/or implemented slices

## Now
1. `FB-003` Backlog consolidation cadence execution
- Status: `Now`
- Goal: bi-weekly consolidated artifact output.
- Exit: one stable artifact per cycle, no duplicate active items across source docs.

2. `FB-006` FCFF-WACC + SBC dilution policy remediation
- Status: `Now`
- Source: `fundamental-fcff-wacc-and-sbc-dilution-remediation-plan-2026-03-08.md`.
- Why: DCF formula-policy still uses CAPM-cost-of-equity proxy as WACC and SBC addback path; needs enterprise-grade correction.
- Exit: S1/S2 implemented and validated, S3 design deferred as planned.


## Next
1. `FB-005` AAPL consensus-anchor reliability + dcf_standard bias remediation
- Status: `Next`
- Source: `fundamental-aapl-consensus-anchor-remediation-plan-2026-03-07.md`.
- Why: AAPL 實跑 `target_mean_price` 回退 yfinance，且相對主流共識仍顯著偏保守。
- Exit: consensus applied/fallback reason 可觀測，AAPL consensus gap 回放顯著收斂。

2. `FB-001` Extend base guardrail to `dcf_standard`
- Status: `Next`
- Source: `fundamental-base-assumption-guardrail-requirement-breakdown-2026-03-05`.
- Why: current guardrail path is `dcf_growth`-first.
- Exit: `dcf_standard` emits `raw/guarded` diagnostics and regression green.

3. `FB-002` Productionize monitoring thresholds
- Status: `Next`
- Source: guardrail/backtest stream.
- Why: gates exist, but production cohort thresholds still need hardening.
- Exit: fixed thresholds for `extreme_upside_rate`, `guardrail_hit_rate`, `consensus_gap_distribution` with release criteria.

4. `FB-004` Formalize bi-weekly consolidation run output
- Status: `Next`
- Source: consolidation governance stream.
- Why: avoid drift between active docs and master backlog.
- Exit: each cycle records source inventory, archived docs, and unresolved assumptions.

5. `FB-033` Dynamic-parameter enterprise alignment and consensus-relative convergence
- Status: `Next`
- Source: `fundamental-dynamic-parameter-enterprise-alignment-plan-2026-03-09.md`.
- Why: current dynamic-parameter stack exhibits structural conservative/optimistic asymmetry across variants and inconsistent consensus quality handling.
- Exit: cohort median `|consensus_gap_pct|` reaches `<=10%~15%` with auditable `raw/guarded/calibrated` traces.

## Later
1. `FB-020` Sensitivity Phase 2 (model-specific dimensions for non-DCF)
- Status: `Later`
- Source: `fundamental-valuation-sensitivity-requirement-breakdown-2026-03-05`.

2. `FB-021` Sensitivity Phase 3 (2D heatmap full-grid, e.g. `wacc x terminal_growth`)
- Status: `Later`
- Source: `fundamental-valuation-sensitivity-requirement-breakdown-2026-03-05`.

## Blocked
- None.

## Done (Code-Verified)
1. `FB-010` Forward signal source semantic split (`xbrl_auto`)
- Evidence: `forward_signals.py`, related tests.

2. `FB-011` CAPM market fallback ladder with assumption traceability
- Evidence: `capm_market_defaults_service.py`, param builder tests.

3. `FB-012` Forward signal calibration mapping and pipeline/runbook
- Evidence: calibration modules, scripts, validators, runbook, tests.

4. `FB-013` Base assumption guardrail v1 on `dcf_growth` plus metadata/UI visibility
- Evidence: dcf payload guardrail hook, assumption/update services, frontend parser/output tests.

5. `FB-014` Sensitivity v1 (DCF one-way shocks) plus diagnostics/UI
- Evidence: sensitivity contracts/service, calculator integration, tests.

6. `FB-015` Backtest monitoring metrics plus gating (`exit code 4`)
- Evidence: backtest report/runtime/runner updates, tests, runbook.

7. `FB-030` Replay input-contract migration (remove log-coupled replay gate)
- Evidence: replay input contracts, replay checks script, release gate manifest path, CI workflow migration, tests.

8. `FB-031` P2 conservative-path replay observability completion
- Evidence: terminal-growth metadata path in parameterization result, replay report metadata-first extraction, replay gate hard-check (`terminal_growth_path_missing`), tests and runbook/docs updated.

9. `FB-032` GOOG shares-scope + reinvestment remediation (`S1-S4`)
- Evidence: shares-scope policy治理、reinvestment guardrail、replay/backtest diagnostics、monitoring gate 指標與測試完成。

## Superseded
1. `fundamental-valuation-bias-remediation-plan-2026-03-04`
- Status: `Superseded`.
- Reason: core slices implemented and absorbed into current streams.

2. `fundamental-forward-signal-calibration-mapping-plan-2026-03-04`
- Status: `Superseded`.
- Reason: core implementation complete; now governed by cadence/runbook/release gate.

## Active Source Docs (Not Superseded)
1. `finance-agent-core/docs/backlog/fundamental-base-assumption-guardrail-requirement-breakdown-2026-03-05.md`
2. `finance-agent-core/docs/backlog/fundamental-valuation-sensitivity-requirement-breakdown-2026-03-05.md`
3. `finance-agent-core/docs/backlog/fundamental-replay-input-contract-migration-plan-2026-03-07.md`
4. `finance-agent-core/docs/backlog/fundamental-aapl-consensus-anchor-remediation-plan-2026-03-07.md`
5. `finance-agent-core/docs/backlog/fundamental-fcff-wacc-and-sbc-dilution-remediation-plan-2026-03-08.md`
6. `finance-agent-core/docs/backlog/fundamental-p2-conservative-path-replay-remediation-plan-2026-03-08.md`
7. `finance-agent-core/docs/backlog/fundamental-goog-shares-scope-and-reinvestment-remediation-plan-2026-03-08.md`
8. `finance-agent-core/docs/backlog/fundamental-dynamic-parameter-enterprise-alignment-plan-2026-03-09.md`

## Archived Source Docs
1. `finance-agent-core/docs/backlog/archive/fundamental-valuation-bias-remediation-plan-2026-03-04.md`
2. `finance-agent-core/docs/backlog/archive/fundamental-forward-signal-calibration-mapping-plan-2026-03-04.md`

## Consolidation Notes (2026-03-07)
1. Added `FB-005` for AAPL consensus-anchor remediation and registered new source doc.
2. Open assumptions:
- `dcf_standard` guardrail rollout remains pending.
- production monitoring threshold tuning remains pending (cohort coverage rule not fixed yet).

## Consolidation Notes (2026-03-09)
1. Added `FB-033` as the new governing backlog stream for enterprise-grade dynamic-parameter alignment.
2. Locked requirements: cohort KPI `|gap| <=10%~15%`, nominal-only long-run growth policy, single-source consensus mandatory down-weight, bi-weekly profile update with replay evidence.

## Consolidation Rules (Bi-weekly)
1. Review code and tests first, then update backlog statuses.
2. Any item marked `Superseded` must include concrete code evidence.
3. New fundamental backlog docs must be registered here before execution.
4. If conflict exists between source docs, this master backlog is execution authority.
