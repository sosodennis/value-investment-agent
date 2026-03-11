# Fundamental Live Replay Cohort Checklist (S23, CI)

## Release Metadata

- Date: 2026-03-09
- Owner: Codex (`agent-refactor-executor`)
- Scope: CI wiring for live replay cohort gate (`FB-034-S23`)
- Workflow: `.github/workflows/monorepo-contract-gates.yml`
- Runner command: `scripts/run_fundamental_live_replay_cohort_gate.py --config config/fundamental_live_replay_cohort_config_ci.json --cycle-tag ci`

## CI Config

- Config path: `finance-agent-core/config/fundamental_live_replay_cohort_config_ci.json`
- discover root: `tests/fixtures/fundamental_replay_inputs`
- ticker allowlist: `AAPL,NVDA`
- thresholds: `min_cases=2`, `min_unique_tickers=2`, `min_pass_rate=1.0`

## Evidence Snapshot

- run summary: `reports/fundamental_live_replay_cohort_run_ci.json`
- manifest: `reports/fundamental_replay_manifest_live_ci.json`
- replay checks: `reports/fundamental_replay_checks_report_live_ci.json`
- cohort gate: `reports/fundamental_replay_cohort_gate_ci.json`
- gate result: `gate_passed=true`

## Decision

- Release decision: `Approve` (CI integration path)
- Reason: workflow can execute live replay cohort gate and upload artifacts in one pass.
