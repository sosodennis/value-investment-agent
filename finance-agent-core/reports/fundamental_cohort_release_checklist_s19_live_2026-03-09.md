# Fundamental Live Replay Cohort Checklist (S19)

## Release Metadata

- Date: 2026-03-09
- Owner: Codex (`agent-refactor-executor`)
- Scope: live replay cohort governance hardening (`FB-034-S19`)
- Manifest path: `finance-agent-core/reports/fundamental_replay_manifest_live_s19.json`
- Staged input root: `finance-agent-core/reports/fundamental_replay_inputs/live_s19`
- Replay report path: `finance-agent-core/reports/fundamental_replay_checks_report_live_s19.json`
- Cohort gate report path: `finance-agent-core/reports/fundamental_replay_cohort_gate_s19.json`

## Gate Configuration

- `min_cases`: `4`
- `min_unique_tickers`: `4`
- `min_pass_rate`: `1.0`
- `require_relative_input_paths`: `true`
- `require_input_root`: `reports/fundamental_replay_inputs/live_s19`

## Evidence Snapshot

- `manifest_cases`: `4`
- `manifest_unique_tickers`: `4` (`AAPL`, `MSFT`, `GOOG`, `NVDA`)
- `manifest_absolute_input_path_count`: `0`
- `manifest_outside_required_root_count`: `0`
- `replay_total_cases`: `4`
- `replay_failed_cases`: `0`
- `replay_pass_rate`: `1.0`

## Decision

- Release decision: `Approve` (for live replay cohort gating path)
- Reason: staged durable input path + strict path/coverage/pass-rate gates all passed.
- Follow-up: connect manifest `--inputs` discovery to artifact export pipeline to remove manual list maintenance.
