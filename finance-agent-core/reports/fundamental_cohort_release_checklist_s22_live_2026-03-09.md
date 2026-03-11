# Fundamental Live Replay Cohort Checklist (S22)

## Release Metadata

- Date: 2026-03-09
- Owner: Codex (`agent-refactor-executor`)
- Scope: config/env driven live replay cohort automation (`FB-034-S22`)
- Runner: `finance-agent-core/scripts/run_fundamental_live_replay_cohort_gate.py`
- Config: `finance-agent-core/config/fundamental_live_replay_cohort_config.json`
- Run summary path: `finance-agent-core/reports/fundamental_live_replay_cohort_run_s22.json`
- Manifest path: `finance-agent-core/reports/fundamental_replay_manifest_live_s22_live.json`
- Replay report path: `finance-agent-core/reports/fundamental_replay_checks_report_live_s22_live.json`
- Cohort gate report path: `finance-agent-core/reports/fundamental_replay_cohort_gate_s22_live.json`

## Runtime Configuration

- `FUNDAMENTAL_LIVE_REPLAY_DISCOVER_ROOT`: `/tmp/fundamental-replay-inputs`
- profile: `live_cohort_v1`
- cycle tag: `s22_live`

## Evidence Snapshot

- `manifest_cases`: `4`
- `manifest_unique_tickers`: `4` (`AAPL`, `MSFT`, `GOOG`, `NVDA`)
- `manifest_absolute_input_path_count`: `0`
- `manifest_outside_required_root_count`: `0`
- `replay_total_cases`: `4`
- `replay_failed_cases`: `0`
- `replay_pass_rate`: `1.0`
- `gate_passed`: `true`

## Decision

- Release decision: `Approve` (for one-command live cohort automation path)
- Reason: config/env driven runner produced full artifacts and strict gate passed.
- Follow-up: wire `FUNDAMENTAL_LIVE_REPLAY_DISCOVER_ROOT` from deployment artifact-export sink.
