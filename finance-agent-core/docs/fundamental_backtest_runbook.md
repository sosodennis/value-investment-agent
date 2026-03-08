# Fundamental Backtest Runbook

This runbook covers the minimal backtest workflow for Sprint `FA-303`.

## Files

- Dataset: `finance-agent-core/tests/fixtures/fundamental_backtest_cases.json`
- Baseline: `finance-agent-core/tests/fixtures/fundamental_backtest_baseline.json`
- Runner: `finance-agent-core/scripts/run_fundamental_backtest.py`
- Calibration validator: `finance-agent-core/scripts/validate_forward_signal_calibration_artifact.py`
- Release gate script: `finance-agent-core/scripts/run_fundamental_release_gate.sh`
- Report output: `finance-agent-core/reports/fundamental_backtest_report.json`

## Commands

1. Validate calibration artifact (release gate prerequisite):

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run --project finance-agent-core python finance-agent-core/scripts/validate_forward_signal_calibration_artifact.py
```

2. Rebuild baseline from current engine outputs:

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run --project finance-agent-core python finance-agent-core/scripts/run_fundamental_backtest.py --update-baseline
```

3. Run comparison against baseline:

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run --project finance-agent-core python finance-agent-core/scripts/run_fundamental_backtest.py
```

Optional: override monitoring gates during release diagnostics:

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run --project finance-agent-core python finance-agent-core/scripts/run_fundamental_backtest.py \
  --max-extreme-upside-rate 0.30 \
  --min-guardrail-hit-rate 0.00 \
  --min-reinvestment-guardrail-hit-rate 0.00 \
  --max-shares-scope-mismatch-rate 1.00 \
  --max-consensus-gap-p90-abs 0.60 \
  --min-consensus-gap-count 20
```

4. Run CI-equivalent release gate locally:

```bash
bash finance-agent-core/scripts/run_fundamental_release_gate.sh
```

Optional: include replay contract checks from structured manifest input:

```bash
FUNDAMENTAL_REPLAY_MANIFEST_PATH="tests/fixtures/fundamental_replay_manifest_ci.json" \
bash finance-agent-core/scripts/run_fundamental_release_gate.sh
```

Run replay checks standalone:

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run --project finance-agent-core python finance-agent-core/scripts/run_fundamental_replay_checks.py \
  --manifest finance-agent-core/tests/fixtures/fundamental_replay_manifest_ci.json \
  --report finance-agent-core/reports/fundamental_replay_checks_report_ci.json
```

Replay contract gate now hard-checks terminal-growth replay fields for each successful
case:

1. `replayed_terminal_growth_fallback_mode`
2. `replayed_terminal_growth_anchor_source`

Missing fields are reported as `error_code=terminal_growth_path_missing` and will fail
release-gate with exit code `5`.

## CI Integration

- Workflow: `.github/workflows/monorepo-contract-gates.yml`
- Job: `fundamental-release-gate`
- Output artifact: `fundamental-backtest-report` (`finance-agent-core/reports/fundamental_backtest_report_ci.json`)
- Note: release gate script still attempts backtest report generation even when calibration validator fails, so CI can upload a diagnostic report.

## Exit Codes

- `0`: all cases pass, no drifts, no issues.
- `1`: one or more case execution errors.
- `2`: drift detected or baseline consistency issues detected.
- `3`: calibration artifact gate failed (runner degraded to embedded default mapping).
- `4`: monitoring gate failed (`extreme_upside_rate` / `guardrail_hit_rate` / `reinvestment_guardrail_hit_rate` / `shares_scope_mismatch_rate` / `consensus_gap_distribution`).
- `5`: replay contract gate failed (`FUNDAMENTAL_REPLAY_MANIFEST_PATH` run failed with one or more replay `error_code`).

## Report Fields

- `summary.total_cases`: total cases in dataset.
- `summary.ok`: successful valuation cases.
- `summary.errors`: failed valuation cases.
- `summary.drift_count`: number of numeric drift points.
- `summary.issue_count`: missing baseline/model mismatch issues.
- `summary.calibration_gate_passed`: whether calibration artifact gate passed.
- `summary.extreme_upside_rate`: fraction of cases where `upside_potential > +80%`.
- `summary.guardrail_hit_rate`: fraction of cases where base guardrail was applied (`guardrail_hit` or component flags).
- `summary.reinvestment_guardrail_hit_rate`: fraction of cases where reinvestment guardrail was applied (`base_capex_guardrail_applied` or `base_wc_guardrail_applied`).
- `summary.shares_scope_mismatch_rate`: fraction of cases with unresolved share-scope mismatch (`shares_scope_mismatch_detected=true` and not resolved).
- `summary.consensus_gap_distribution`: aggregate distribution stats (`available_count`, `median`, `p10`, `p90`, `mean`, `mean_abs`, `p90_abs`, `max_abs`) when consensus anchors exist.
- `calibration.mapping_version`: loaded mapping version.
- `calibration.mapping_source`: `env_path` / `default_artifact` / `embedded_default`.
- `calibration.mapping_path`: artifact path attempted by loader.
- `calibration.degraded_reason`: populated when artifact load/parse failed.
- `results[]`: per-case status and extracted key metrics.
- `drifts[]`: metric-level baseline vs current differences.

## Default Monitoring Gates

- `max_extreme_upside_rate=0.30`
- `min_guardrail_hit_rate=0.00`
- `min_reinvestment_guardrail_hit_rate=0.00`
- `max_shares_scope_mismatch_rate=1.00`
- `max_consensus_gap_p90_abs=0.60`
- `min_consensus_gap_count=2` (set to `20+` for production-like cohort gates)
