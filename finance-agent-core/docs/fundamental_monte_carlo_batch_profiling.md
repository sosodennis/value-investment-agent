# Fundamental Monte Carlo Batch Profiling

This runbook defines how to profile the fundamental Monte Carlo batch kernels and
generate an auditable performance artifact.

## Scope

- Focus: batch evaluator kernel performance for `saas`, `bank`, `reit`.
- Compare: `reference` (pre-optimization loop style) vs `optimized` (vectorized style).
- Sizes: `1000` and `10000` iterations.
- Output:
  - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/reports/fundamental_mc_kernel_profile.json`
  - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/reports/fundamental_mc_kernel_profile.md`

## Command

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run --project finance-agent-core \
  python finance-agent-core/scripts/profile_monte_carlo_batch_kernels.py \
  --iterations 1000 10000 --repeats 9 --seed 42
```

## Acceptance Gate

1. `max_abs_diff <= tolerance` for each `(model, iteration)` row.
2. `saas` and `bank` should show positive `improvement_pct` at 10k iteration.
3. Store generated reports under `finance-agent-core/reports/` for review.
