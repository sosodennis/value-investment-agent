# Fundamental Cohort Release Checklist (S13, prod profile)

## Release Metadata

- Date: 2026-03-09
- Owner: Codex (`agent-refactor-executor`)
- Candidate artifact version: `forward_signal_calibration_v1_2026_03_04`
- Mapping/profile path: `config/fundamental_gate_profiles.json` (`prod_cohort_v1`)
- Backtest report path: `finance-agent-core/reports/fundamental_backtest_report_s13_prod.json`
- Replay report path: `finance-agent-core/reports/fundamental_replay_checks_report_s13_prod.json`
- Snapshot path: `finance-agent-core/reports/fundamental_release_gate_snapshot_s13_prod.json`

## Cohort Scope

- Tickers: fixture cohort (`tests/fixtures/fundamental_backtest_cases.json`)
- Cohort case count target: 6
- Consensus coverage minimum: 20 (from `prod_cohort_v1`)

## Gate Configuration (actual)

- `max_consensus_gap_median_abs`: `0.15`
- `max_consensus_gap_p90_abs`: `0.60`
- `min_consensus_gap_count`: `20`
- `max_consensus_degraded_rate`: `0.80`
- `min_consensus_confidence_weight`: `0.30`
- `min_consensus_quality_count`: `20`
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
- release gate exit code: `4`
- blocking issue: `monitoring_gate_failed:consensus_gap_available_count=2<min:20`

## Governance Checks

1. Single-source consensus degraded path observed and not treated as high confidence.
- Result: `Pass`
- Evidence: no single-source replay error code; replay checks passed.

2. Canonical market datum normalization present (`target_mean_price.horizon=12m`, `shares_outstanding.shares_scope` present).
- Result: `Pass`
- Evidence: snapshot validator passed (`gate_passed=true`).

3. Replay trace contract gate satisfied (`trace_contract_pass_rate >= min_replay_trace_contract_pass_rate`).
- Result: `Pass`
- Evidence: `1.0 >= 1.0`

4. Release gate exit code:
- Result: `Fail`
- Evidence: exit code `4` due insufficient consensus coverage for prod gate (`2 < 20`).

## Decision

- Release decision: `Reject` (for `prod_cohort_v1` profile)
- Reason: failed production coverage threshold (`min_consensus_gap_count=20`) on current small fixture cohort.
- Rollback artifact (if needed): keep previous approved profile/mapping artifacts.
- Follow-up actions:
  - run on a production-like cohort with `consensus_gap_available_count >= 20`;
  - collect wider replay/backtest evidence set before production promotion.
