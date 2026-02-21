# Fundamental Backtest Runbook

This runbook covers the minimal backtest workflow for Sprint `FA-303`.

## Files

- Dataset: `finance-agent-core/tests/fixtures/fundamental_backtest_cases.json`
- Baseline: `finance-agent-core/tests/fixtures/fundamental_backtest_baseline.json`
- Runner: `finance-agent-core/scripts/run_fundamental_backtest.py`
- Report output: `finance-agent-core/reports/fundamental_backtest_report.json`

## Commands

1. Rebuild baseline from current engine outputs:

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run --project finance-agent-core python finance-agent-core/scripts/run_fundamental_backtest.py --update-baseline
```

2. Run comparison against baseline:

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run --project finance-agent-core python finance-agent-core/scripts/run_fundamental_backtest.py
```

## Exit Codes

- `0`: all cases pass, no drifts, no issues.
- `1`: one or more case execution errors.
- `2`: drift detected or baseline consistency issues detected.

## Report Fields

- `summary.total_cases`: total cases in dataset.
- `summary.ok`: successful valuation cases.
- `summary.errors`: failed valuation cases.
- `summary.drift_count`: number of numeric drift points.
- `summary.issue_count`: missing baseline/model mismatch issues.
- `results[]`: per-case status and extracted key metrics.
- `drifts[]`: metric-level baseline vs current differences.
