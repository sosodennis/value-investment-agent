# Fundamental Replay Input Contract

## Purpose

Define stable, log-independent inputs for replay/debug/gate workflows.

## Schemas

1. `valuation_replay_input_v2`
- Single replay case input.

2. `valuation_replay_manifest_v1`
- Batch replay manifest, referencing multiple input files.

## `valuation_replay_input_v2`

Required fields:

1. `schema_version`: literal `valuation_replay_input_v2`
2. `model_type`: valuation model id (for example `dcf_growth`, `dcf_standard`)
3. `reports`: canonical financial reports array

Optional fields:

1. `ticker`
2. `market_snapshot`
3. `forward_signals`
4. `staleness_mode` (`snapshot` or `recompute`, default `snapshot`)
5. `override` (object, deep-merged before replay build)
6. `baseline`

`baseline` optional object fields:

1. `params_dump`
2. `calculation_metrics`
3. `assumptions`
4. `build_metadata`
5. `diagnostics`

`baseline.build_metadata` terminal-growth observability contract (recommended):

1. `data_freshness.terminal_growth_path.terminal_growth_fallback_mode`
2. `data_freshness.terminal_growth_path.terminal_growth_anchor_source`
3. `data_freshness.terminal_growth_path.long_run_growth_anchor_staleness`
   (`is_stale/days/max_days`)

Replay report prefers these metadata fields. If absent, replay will fallback to
assumption-string extraction.

`market_snapshot.market_datums` canonical contract additions (recommended):

1. `target_mean_price.horizon`:
- Canonical expected value: `12m`.
- Runtime normalizes missing value to `12m` for market snapshot persistence.
2. `shares_outstanding.shares_scope`:
- Canonical expected values: `market_class`, `filing_consolidated`, `market_class_harmonized`, `unknown`.
- Runtime normalizes missing value to `unknown` for market snapshot persistence.
3. `target_mean_price.fallback_reason`:
- Includes governance reasons such as `single_source_consensus`.
4. `target_mean_price.quality_flags`:
- Includes `consensus_fallback` and contract normalization flags when applicable.

## `valuation_replay_manifest_v1`

Required fields:

1. `schema_version`: literal `valuation_replay_manifest_v1`
2. `cases`: non-empty array

Each case requires:

1. `case_id`
2. `input_path` (relative path resolved from manifest directory, or absolute path)

## CLI Usage

Single replay:

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run --project finance-agent-core python finance-agent-core/scripts/replay_fundamental_valuation.py \
  --input finance-agent-core/tests/fixtures/fundamental_replay_inputs/aapl.replay.json \
  --override-json /tmp/replay-override.json
```

Batch replay:

```bash
UV_CACHE_DIR=/tmp/.uv-cache uv run --project finance-agent-core python finance-agent-core/scripts/run_fundamental_replay_checks.py \
  --manifest finance-agent-core/tests/fixtures/fundamental_replay_manifest_ci.json \
  --report finance-agent-core/reports/fundamental_replay_checks_report_ci.json
```

## Replay Report Path Fields

Key report fields for terminal growth path observability:

1. `baseline_terminal_growth_fallback_mode`
2. `replayed_terminal_growth_fallback_mode`
3. `baseline_terminal_growth_anchor_source`
4. `replayed_terminal_growth_anchor_source`

Expected values:

1. Fallback mode: `default_only` or `filing_first_then_default`
2. Anchor source: `market`, `filing`, or `default`

Key report fields for forward-signal trace observability:

1. `replayed_forward_signal.calibration_applied`
2. `replayed_forward_signal.mapping_version`
3. `replayed_forward_signal.growth_adjustment_basis_points`
4. `replayed_forward_signal.margin_adjustment_basis_points`
5. `replayed_forward_signal.raw_growth_adjustment_basis_points`
6. `replayed_forward_signal.raw_margin_adjustment_basis_points`
7. `replayed_forward_signal.calibration_degraded_reason` (key required, value can be `null`)

Replay checks summary fields used by release gate:

1. `summary.total_cases`
2. `summary.passed_cases`
3. `summary.failed_cases`
4. `summary.trace_contract_pass_rate`
5. `summary.quality_block_rate`
6. `summary.cache_hit_rate`
7. `summary.warm_latency_p90_ms`
8. `summary.cold_latency_p90_ms`
