# Legacy Code Audit Register
Date: 2026-02-16
Policy: Zero compatibility. Delete legacy paths once replacement is verified.

Status legend:
1. `PENDING`: not analyzed yet
2. `IN_REVIEW`: evidence collected, action not executed
3. `DONE`: action completed and gates passed

| Package / Module | Issue Type | Evidence | Action | Test Evidence | Status |
|---|---|---|---|---|---|
| `src/infrastructure/serialization.py` | Unreferenced module candidate | `rg -n "FinancialSafeSerializer|src\\.infrastructure\\.serialization"` returns no consumers | DELETE | `ruff` pass + protocol/mappers/debate/news suites (20 passed) + contract suites (15 passed) | DONE |
| `src/common/**` | Old namespace residue | no runtime files remained; only stale cache directories | DELETE directory residue | no old imports (`rg -n "src\\.common\\."` empty) + suites above | DONE |
| `src/shared/application/**` | Old namespace residue | no runtime files remained; only stale cache directories | DELETE directory residue | no old imports (`rg -n "src\\.shared\\.(application|data|domain|interface)"` empty) + suites above | DONE |
| `src/shared/data/**` | Old namespace residue | no runtime files remained; only stale cache directories | DELETE directory residue | no old imports (`rg -n "src\\.shared\\.(application|data|domain|interface)"` empty) + suites above | DONE |
| `src/shared/domain/**` | Old namespace residue | no runtime files remained; only stale cache directories | DELETE directory residue | no old imports (`rg -n "src\\.shared\\.(application|data|domain|interface)"` empty) + suites above | DONE |
| `src/shared/interface/**` | Old namespace residue | no runtime files remained; only stale cache directories | DELETE directory residue | no old imports (`rg -n "src\\.shared\\.(application|data|domain|interface)"` empty) + suites above | DONE |
| `src/interface/artifacts/*` | Potential parser/model overlap | needs module-by-module review against registry | KEEP/MERGE per finding | contract suites | PENDING |
| `src/interface/events/*` | Potential adapter overlap | needs module-by-module review | KEEP/MERGE per finding | protocol suites | PENDING |
| `src/services/*` | Port-wrapper duplication | verify overlap with typed ports | KEEP/MERGE per finding | core + contract suites | PENDING |
| `src/workflow/*` | Wrapper/legacy scaffold risk | verify orchestration responsibilities | KEEP/MOVE/DELETE per finding | core suites | PENDING |
| `src/agents/intent/*` | Layer boundary drift risk | per-layer audit pending | KEEP/MOVE/MERGE/DELETE | agent + core suites | PENDING |
| `src/agents/fundamental/*` | Layer boundary drift risk | per-layer audit pending | KEEP/MOVE/MERGE/DELETE | agent + contract suites | PENDING |
| `src/agents/news/*` | Layer boundary drift risk | per-layer audit pending | KEEP/MOVE/MERGE/DELETE | agent + core suites | PENDING |
| `src/agents/technical/*` | Layer boundary drift risk | per-layer audit pending | KEEP/MOVE/MERGE/DELETE | agent + core suites | PENDING |
| `src/agents/debate/*` | Layer boundary drift risk | per-layer audit pending | KEEP/MOVE/MERGE/DELETE | agent + core suites | PENDING |
