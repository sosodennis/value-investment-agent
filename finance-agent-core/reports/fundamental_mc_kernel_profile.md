# Fundamental MC Batch Kernel Profiling

- generated_at: `2026-02-24T15:11:28.610106+00:00`
- tolerance: `1e-09`

| Model | Iterations | Ref p50 (ms) | Opt p50 (ms) | Speedup | Improvement | Max Abs Diff | MAE |
|---|---:|---:|---:|---:|---:|---:|---:|
| saas | 1000 | 0.2402 | 0.2200 | 1.0920x | 8.43% | 0 | 0 |
| bank | 1000 | 0.1489 | 0.1375 | 1.0828x | 7.64% | 0 | 0 |
| reit | 1000 | 0.0069 | 0.0066 | 1.0349x | 3.37% | 0 | 0 |
| saas | 10000 | 1.5357 | 1.5307 | 1.0032x | 0.32% | 0 | 0 |
| bank | 10000 | 1.0507 | 1.0387 | 1.0115x | 1.14% | 0 | 0 |
| reit | 10000 | 0.0264 | 0.0263 | 1.0056x | 0.55% | 0 | 0 |

## Gate

- PASS numerical consistency within tolerance.
