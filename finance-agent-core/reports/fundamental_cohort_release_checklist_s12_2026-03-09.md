# Fundamental Cohort Release Checklist (S12)

## Release Metadata

- Date: 2026-03-09
- Owner: Codex (`agent-refactor-executor`)
- Candidate artifact version: `forward_signal_calibration_v1_2026_03_04`
- Mapping/profile path: `config/fundamental_gate_profiles.json` (`ci_cohort_v1`)
- Backtest report path: `finance-agent-core/reports/fundamental_backtest_report_s12.json`
- Replay report path: `finance-agent-core/reports/fundamental_replay_checks_report_s12.json`
- Snapshot path: `finance-agent-core/reports/fundamental_release_gate_snapshot_s12.json`

## Cohort Scope

- Tickers: fixture cohort (`tests/fixtures/fundamental_backtest_cases.json`)
- Cohort case count target: 6
- Consensus coverage minimum: 2 (from `ci_cohort_v1`)

## Gate Configuration (actual)

- `max_consensus_gap_median_abs`: `0.15`
- `max_consensus_gap_p90_abs`: `0.60`
- `min_consensus_gap_count`: `2`
- `max_consensus_degraded_rate`: `1.00`
- `min_consensus_confidence_weight`: `0.00`
- `min_consensus_quality_count`: `0`
- `min_replay_trace_contract_pass_rate`: `1.00`

## Evidence Snapshot

- `summary.total_cases`: `6`
- `summary.ok`: `6`
- `summary.errors`: `0`
- `summary.consensus_gap_distribution.available_count`: `2`
- `summary.consensus_gap_distribution.median`: `-0.0955523731177651`
- `summary.consensus_gap_distribution.p90_abs`: `0.184176200189188`
- `summary.consensus_degraded_rate`: `0.0`
- `summary.consensus_confidence_weight_avg`: `0.0`
- `summary.shares_scope_mismatch_rate`: `0.0`
- `summary.guardrail_hit_rate`: `0.0`
- `summary.replay_checks.total_cases`: `2`
- `summary.replay_checks.passed_cases`: `2`
- `summary.replay_checks.failed_cases`: `0`
- `summary.replay_checks.trace_contract_pass_rate`: `1.0`
- `replay_error_codes`: `[]`
- release gate exit code: `0`

## Governance Checks

1. Single-source consensus degraded path observed and not treated as high confidence.
- Result: `Pass` (no violation in this run; replay/backtest issues empty)
- Evidence: `fundamental_release_gate_snapshot_s12.json -> issues=[]`

2. Canonical market datum normalization present (`target_mean_price.horizon=12m`, `shares_outstanding.shares_scope` present).
- Result: `Pass`
- Evidence: FB-034 code path and snapshot validation passed (`gate_passed=true`).

3. Replay trace contract gate satisfied (`trace_contract_pass_rate >= min_replay_trace_contract_pass_rate`).
- Result: `Pass`
- Evidence: `1.0 >= 1.0`

4. Release gate exit code:
- Result: `Pass`
- Evidence: exit code `0`

## Decision

- Release decision: `Approve` (for `ci_cohort_v1` profile)
- Reason: all configured CI thresholds satisfied; replay trace contract pass-rate satisfied; snapshot validator passed.
- Rollback artifact (if needed): previous mapping/profile artifacts.
- Follow-up actions:
  - run the same checklist under `prod_cohort_v1` with production cohort size/coverage before production promotion.
