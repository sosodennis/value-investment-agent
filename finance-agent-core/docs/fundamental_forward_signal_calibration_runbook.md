# Fundamental Forward Signal Calibration Runbook

## Goal

Maintain a reproducible offline calibration flow so runtime policy keeps using internal DCF output while calibration magnitude is updated from replay evidence.

## Inputs

1. Replay report JSON (`results[]`) with per-ticker:
- `ticker`
- `current_price`
- `intrinsic_value`
- `forward_signal_summary`
- optional `target_consensus_mean_price` or `target_mean_price`
2. (Optional) live market data fallback for missing target anchors.

## Pipeline

1. Build observations and fit artifact in one command:

```bash
uv run --project finance-agent-core python scripts/run_forward_signal_calibration_pipeline.py \
  --replay-report reports/fundamental_cohort_replay_s4.json \
  --dataset-output reports/forward_signal_calibration_dataset.jsonl \
  --artifact-output reports/forward_signal_calibration.mapping.json \
  --mapping-version forward_signal_calibration_v2_2026_03_05 \
  --min-samples 120 \
  --report-output reports/forward_signal_calibration_pipeline_report.json
```

2. Validate generated mapping artifact:

```bash
uv run --project finance-agent-core python scripts/validate_forward_signal_calibration_artifact.py \
  --path reports/forward_signal_calibration.mapping.json
```

3. Validate pipeline quality gates:

```bash
uv run --project finance-agent-core python scripts/validate_forward_signal_calibration_pipeline_report.py \
  --path reports/forward_signal_calibration_pipeline_report.json \
  --min-usable-rows 20 \
  --min-anchor-coverage 0.60
```

## Release Gate Integration

Enable pipeline report gate in release script:

```bash
FUNDAMENTAL_REQUIRE_CALIBRATION_PIPELINE_REPORT=1 \
uv run --project finance-agent-core bash scripts/run_fundamental_release_gate.sh \
  reports/fundamental_backtest_report_ci.json \
  reports/forward_signal_calibration_pipeline_report.json
```

Behavior:
- mapping artifact degraded -> release gate exits non-zero.
- pipeline quality gate fail -> release gate exits `4`.

## Suggested Cadence

1. Run pipeline weekly or bi-weekly after replay refresh.
2. Promote new mapping only when:
- artifact validation passes
- pipeline quality gates pass
- backtest/replay regression is non-worsening.

## Rollback

1. Repoint `FUNDAMENTAL_FORWARD_SIGNAL_CALIBRATION_MAPPING_PATH` to previous known-good artifact.
2. If needed, unset override to use built-in default mapping.
