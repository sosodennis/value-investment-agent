# Task Spec: T27 Regime Deterministic Input Alignment

## Objective
Align regime computation with canonical deterministic feature and indicator surfaces while preserving the existing `regime` capability boundary and graceful fallback behavior.

## Scope
- Extend feature snapshots and indicator series with regime-facing inputs such as `ADX_14`, `ATRP_14`, and `BB_BANDWIDTH_20`.
- Update regime compute orchestration to prefer canonical deterministic inputs and log explicit fallback when raw OHLCV recomputation is required.
- Add targeted tests covering both canonical-input and degraded fallback paths.

## Non-goals
- Replace the heuristic regime classifier.
- Remove graceful fallback to OHLCV-derived inputs entirely.
- Introduce new shared-kernel contracts or a second regime subdomain.
