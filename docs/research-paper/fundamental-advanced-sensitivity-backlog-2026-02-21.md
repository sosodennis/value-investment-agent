# Fundamental Advanced Sensitivity Analysis Backlog (2026-02-21)

## Purpose

This document captures a deferred enhancement for advanced global sensitivity analysis in the Fundamental valuation engine. The goal is to revisit implementation later with clear scope, effort, and decision criteria.

## Current State (Already Implemented)

- Monte Carlo distribution outputs (P5/P25/P50/P75/P95, std, diagnostics)
- Correlated sampling support (correlation groups)
- Per-share metric semantics guardrails for valuation preview

## Deferred Topics

### 1. Sobol Global Sensitivity

- What it answers:
  - How much output variance is explained by each input variable (`S1`) and total effect (`ST`)
- Why useful:
  - Quantifies variance attribution, including interaction impact
- Complexity:
  - Medium-high
  - Typical effort: 1.5-3 weeks
- Key risks:
  - Heavy simulation cost
  - Classical Sobol assumes independent inputs; extra design needed under correlated inputs

### 2. Shapley Effects (Global Sensitivity)

- What it answers:
  - Fair variance contribution allocation per variable under dependence/correlation
- Why useful:
  - Strong interpretability for correlated finance drivers
- Complexity:
  - High
  - Typical effort: 3-6 weeks
- Key risks:
  - Significant compute budget
  - Approximation strategy required for tractable runtime

### 3. Interaction Decomposition

- What it answers:
  - Pairwise/higher-order interaction contributions (e.g., growth x margin)
- Why useful:
  - Prevents misleading single-factor explanations
- Complexity:
  - Medium-high (after Sobol foundations)
  - Typical effort: 1-2 weeks
- Key risks:
  - Dimensionality explosion for many variables

### 4. Group Factor Decomposition

- What it answers:
  - Variance contribution by grouped drivers (Growth / Discount / Terminal / Balance Sheet)
- Why useful:
  - Executive-friendly reporting and governance alignment
- Complexity:
  - Medium
  - Typical effort: 3-7 days
- Key risks:
  - Requires stable factor taxonomy and ownership rules

### 5. Stability Tests

- What it answers:
  - Whether sensitivity ranking/conclusions are robust across seeds/windows/bootstrap samples
- Why useful:
  - Avoids unstable or accidental driver conclusions
- Complexity:
  - Medium
  - Typical effort: 4-8 days
- Key risks:
  - Runtime overhead; confidence threshold design

## Recommended Implementation Phasing (When Reopened)

### Phase A: Practical MVP (1-2 weeks)

- Add Monte Carlo driver ranking using Spearman/PRCC
- Add bootstrap confidence intervals for top drivers
- Add `percentile representative scenarios` (P5/P50/P95 nearest sample parameter sets)
- Output contract: `sensitivity_report` + `scenario_representatives`

### Phase B: Enterprise V1 (2-4 additional weeks)

- Add Sobol-based global sensitivity (with explicit input-independence/correlation handling strategy)
- Add interaction decomposition for top-k driver pairs
- Add grouped factor decomposition

### Phase C: Advanced Governance Layer (optional)

- Add Shapley effects for correlated drivers
- Add stability acceptance gates in CI/backtest reporting
- Add markdown report artifacts with audit sections

## Decision Gates Before Implementation

1. Runtime budget:
   - Define max latency per valuation run and async/offline policy
2. Accuracy target:
   - Define acceptable CI width / ranking stability thresholds
3. Scope boundary:
   - Decide supported models in v1 (SaaS, Bank, REIT first)
4. Contract boundary:
   - Confirm frontend payload schema for sensitivity outputs

## Suggested Future Tickets

1. Design `sensitivity_report` JSON schema and parser contract
2. Extend MonteCarloEngine to expose sampled input snapshots for post-analysis
3. Implement PRCC/Spearman ranking + bootstrap CI
4. Add representative percentile scenarios extraction
5. Add UI panel for top drivers + confidence
6. Add baseline regression tests for sensitivity rank stability
7. Add Sobol module (feature-gated by model and iteration threshold)
8. Add interaction/group decomposition module

## Status

- Decision: Deferred
- Rationale: Higher complexity and compute cost; not blocking current valuation correctness
- Revisit trigger: After current valuation pipeline stabilization and regression reporting completion
