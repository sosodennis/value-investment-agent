# Fundamental Cohort Release Checklist (S17, prod profile)

## Release Metadata

- Date: 2026-03-09
- Owner: Codex (`agent-refactor-executor`)
- Candidate artifact version: `forward_signal_calibration_v1_2026_03_04`
- Mapping/profile path: `config/fundamental_gate_profiles.json` (`prod_cohort_v1`)
- Backtest report path: `finance-agent-core/reports/fundamental_backtest_report_s17_prod.json`
- Replay report path: `finance-agent-core/reports/fundamental_replay_checks_report_s17_prod.json`
- Snapshot path: `finance-agent-core/reports/fundamental_release_gate_snapshot_s17_prod.json`
- Stability report path: `finance-agent-core/reports/fundamental_cohort_stability_report_s17_prod.json`
- Cohort dataset path: `finance-agent-core/tests/fixtures/fundamental_backtest_cases_prod_cohort.json`
- Cohort baseline path: `finance-agent-core/tests/fixtures/fundamental_backtest_baseline_prod_cohort.json`

## Cohort Scope

- Tickers: prod-like DCF anchor cohort fixture
- Cohort case count target: 20
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

- `summary.total_cases`: `20`
- `summary.ok`: `20`
- `summary.errors`: `0`
- `summary.consensus_gap_distribution.available_count`: `20`
- `summary.consensus_gap_distribution.median`: `-0.0955523731177651`
- `summary.consensus_gap_distribution.p90_abs`: `0.203286674812741`
- `summary.consensus_degraded_rate`: `0.0`
- `summary.consensus_confidence_weight_avg`: `0.6`
- `summary.shares_scope_mismatch_rate`: `0.0`
- `summary.guardrail_hit_rate`: `0.0`
- `summary.replay_checks.total_cases`: `2`
- `summary.replay_checks.passed_cases`: `2`
- `summary.replay_checks.failed_cases`: `0`
- `summary.replay_checks.trace_contract_pass_rate`: `1.0`
- `replay_error_codes`: `[]`
- release gate exit code: `0`
- rolling stability (`S14+S17`, strict): `Pass` (`summary.stable=true`)

## Governance Checks

1. Single-source consensus degraded path observed and not treated as high confidence.
- Result: `Pass`
- Evidence: no replay/backtest issue; degraded rate remains `0.0` and confidence average `0.6`.

2. Canonical market datum normalization present (`target_mean_price.horizon=12m`, `shares_outstanding.shares_scope` present).
- Result: `Pass`
- Evidence: snapshot validator passed (`gate_passed=true`, issues empty).

3. Replay trace contract gate satisfied (`trace_contract_pass_rate >= min_replay_trace_contract_pass_rate`).
- Result: `Pass`
- Evidence: `1.0 >= 1.0`

4. Release gate exit code:
- Result: `Pass`
- Evidence: exit code `0`

5. Rolling stability strict gate (`--require-stable --min-considered-runs 2`):
- Result: `Pass`
- Evidence: `validate_fundamental_cohort_stability_report.py` returned `gate_passed=true`.

## Decision

- Release decision: `Approve` (for `prod_cohort_v1` under this prod-like cohort fixture)
- Reason: release gate and rolling stability strict gate both pass.
- Rollback artifact (if needed): previous approved mapping/profile artifacts.
- Follow-up actions:
  - continue replacing fixture cohort with broader live production cohort samples to preserve `summary.stable=true` under bi-weekly cadence.
