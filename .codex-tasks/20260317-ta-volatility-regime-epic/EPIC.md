# EPIC: Technical Volatility/Regime/Structure Upgrade

## Goal
Upgrade the technical agent with three deterministic capabilities: ATR-adaptive pattern thresholds, regime-aware signal fusion, and VP-lite market-structure analysis.

## Scope
- T22: ATR-adaptive patterns using OHLC-aware inputs and volatility-scaled thresholds.
- T23: Regime subdomain plus regime-aware fusion.
- T24: VP-lite volume-at-price structure and confluence scoring.
- T25: Semantic/full-report projection migration for regime and structure evidence.
- T26: VP-lite contract completion with POC/VAH/VAL and fidelity metadata.
- T27: Regime deterministic input alignment across features, series, and compute fallback.

## Constraints
- No compatibility shims required.
- Use existing free OHLCV data providers; no paid market-depth integration.
- Keep artifacts/state lightweight and avoid passing large tabular data through graph state.

## Non-goals
- True order-flow / L2 microstructure analytics.
- HMM-first regime modeling.
- Execution-agent semantics or broker actions.

## Follow-up Closure Scope
- Eliminate the remaining review gaps from the 2026-03-17 architecture re-audit.
- Carry deterministic regime/VP evidence through interpretation and report projections.
- Promote VP-lite from node-only output to an explicit profile contract with fidelity markers.
- Align regime inputs with reusable deterministic feature/indicator surfaces while retaining graceful fallback.
