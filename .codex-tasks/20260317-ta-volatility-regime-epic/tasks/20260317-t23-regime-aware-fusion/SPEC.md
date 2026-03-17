# Task Spec: T23 Regime Subdomain + Regime-Aware Fusion

## Objective
Introduce a dedicated regime capability and condition technical signal fusion on the classified market state.

## Scope
- Add a `regime` subdomain with deterministic classification from classic indicators.
- Persist a regime artifact and wire it into fusion inputs.
- Adjust fusion weighting/risk notes based on the regime.

## Non-goals
- HMM or offline statistical regime models.
- Volume profile / VP-lite structure scoring.
