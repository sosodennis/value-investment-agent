# Fundamental Live Replay Cohort Checklist (S20)

## Release Metadata

- Date: 2026-03-09
- Owner: Codex (`agent-refactor-executor`)
- Scope: live replay cohort discovery automation (`FB-034-S20`)
- Manifest path: `finance-agent-core/reports/fundamental_replay_manifest_live_s20.json`
- Staged input root: `finance-agent-core/reports/fundamental_replay_inputs/live_s20`
- Replay report path: `finance-agent-core/reports/fundamental_replay_checks_report_live_s20.json`
- Cohort gate report path: `finance-agent-core/reports/fundamental_replay_cohort_gate_s20.json`

## Discovery Configuration

- `discover_root`: `/tmp/fundamental-replay-inputs`
- `discover_glob`: `*.replay-input*.json`
- `ticker_allowlist`: `AAPL,MSFT,GOOG,NVDA`
- `latest_per_ticker`: `true`
- `fail_on_invalid_input`: `false` (legacy/invalid payload auto-skip)

## Gate Configuration

- `min_cases`: `4`
- `min_unique_tickers`: `4`
- `min_pass_rate`: `1.0`
- `require_relative_input_paths`: `true`
- `require_input_root`: `reports/fundamental_replay_inputs/live_s20`

## Evidence Snapshot

- `manifest_cases`: `4`
- `manifest_unique_tickers`: `4` (`AAPL`, `MSFT`, `GOOG`, `NVDA`)
- `manifest_absolute_input_path_count`: `0`
- `manifest_outside_required_root_count`: `0`
- `replay_total_cases`: `4`
- `replay_failed_cases`: `0`
- `replay_pass_rate`: `1.0`

## Decision

- Release decision: `Approve` (for discovery-based live replay cohort path)
- Reason: directory discovery + staged relative paths + strict cohort gate all passed.
- Follow-up: bind `discover_root` to artifact export sink/environment var to remove manual path assignment.
