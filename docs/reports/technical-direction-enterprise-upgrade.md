# Technical Direction Enterprise Upgrade Report

Date: 2026-03-16

## Executive Summary
We can elevate the current Direction logic from a usable heuristic to an enterprise-grade, auditable decision engine by adding three capabilities.
1. Explainability and audit trace: make every Direction output decomposable into per-timeframe and per-indicator contributions.
2. Calibrated confidence: turn the current internal score into a probability that matches real-world hit rates, validated with reliability diagnostics.
3. Governance and lifecycle: formalize documentation, validation, monitoring, and change control in line with financial model risk management guidance.

These steps directly address the transparency, accountability, and ongoing performance expectations emphasized in model risk management guidance from U.S. regulators. The approach is incremental and can be delivered in phases without breaking the existing product flow.

Key references for enterprise expectations include Federal Reserve SR 11-7 and OCC 2011-12 guidance, which emphasize effective challenge, documentation, validation, ongoing monitoring, and model inventories. The same guidance is adopted across banking agencies.
- [Federal Reserve SR 11-7](https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm)
- [Federal Reserve Supervisory Guidance (full text)](https://www.federalreserve.gov/frrs/guidance/supervisory-guidance-on-model-risk-management.htm)
- [OCC 2011-12 Bulletin](https://www.occ.gov/news-issuances/bulletins/2011/bulletin-2011-12.html)
- [FDIC Adoption Notice](https://www.fdic.gov/news/financial-institution-letters/2017/fil17022.html)

## Current System Behavior (Baseline)
Direction is computed in the signal fusion subdomain by aggregating scores across classic, quant, and pattern indicators per timeframe, then averaging and comparing to a neutral threshold.
- Classic indicators: SMA/EMA/VWAP, RSI/MFI, MACD.
- Quant indicators: FD Z-score, FD OBV Z, FD Bollinger bandwidth.
- Pattern indicators: breakouts, trendlines, support/resistance.
- Overall score = average of timeframe scores. Direction = bullish or bearish if score crosses neutral threshold.

This is coherent and logically consistent, but the output is not currently enterprise transparent because the user cannot see the score decomposition or how the threshold led to the final classification.

## What “Enterprise-Grade” Means Here
Enterprise-grade does not only mean “advanced math.” It also means the output is auditable, governance-ready, and can withstand internal and external scrutiny. These are the core expectations in SR 11-7/OCC guidance.
- Effective challenge: independent parties must be able to see inputs, logic, and constraints to challenge conclusions.
- Validation and monitoring: models must be checked for conceptual soundness, monitored for drift, and tested against outcomes.
- Documentation and inventory: the system must maintain model documentation, validation status, and a clear inventory of what is in production.

These principles are explicit in SR 11-7 and OCC guidance.
- [Federal Reserve SR 11-7](https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm)
- [Federal Reserve Supervisory Guidance (full text)](https://www.federalreserve.gov/frrs/guidance/supervisory-guidance-on-model-risk-management.htm)
- [OCC 2011-12 Bulletin](https://www.occ.gov/news-issuances/bulletins/2011/bulletin-2011-12.html)

## Gap Analysis
1. Explainability gap
The current Direction output is not accompanied by a full score breakdown. This prevents effective challenge and audit trace.

2. Calibration gap
Confidence is derived from internal score magnitude rather than calibrated probabilities. This is less defensible for enterprise use. Calibration is standard practice in predictive systems that present probability-like outputs.
- [scikit-learn calibration reference](https://scikit-learn.org/stable/modules/calibration.html)

3. Governance and lifecycle gap
There is no model inventory or validation status visible to stakeholders. SR 11-7 and OCC guidance emphasize inventories, documentation, and periodic review.
- [Federal Reserve SR 11-7](https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm)

## Enterprise Upgrade Architecture

### A) Direction Explainability Pack
Goal: Every Direction result can be fully decomposed and audited.

New Artifact: `ta_direction_scorecard`
- `timeframe_scores`: per timeframe classic/quant/pattern score, label, and thresholds.
- `indicator_contributions`: each indicator’s contribution value.
- `thresholds`: neutral threshold and indicator-level decision boundaries.
- `conflict_reasons`: explicit contradictions across sources.
- `model_version`: fusion logic version.

UI Output:
- Direction card shows “Score Breakdown” toggle.
- Displays per timeframe and per indicator contribution.
- Shows confidence source tag: “Calibrated” or “Raw”.

Why enterprise-grade:
- Enables effective challenge by showing the decision chain.
- Matches governance requirements for documentation and auditability.
- [Federal Reserve SR 11-7](https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm)

### B) Confidence Calibration
Goal: Confidence corresponds to actual hit rate probability, not only internal strength.

New Subdomain Capability: `calibration_runtime`
- Generate labeled outcomes using walk-forward windows.
- Fit calibration models (sigmoid or isotonic).
- Output `ta_calibration_report` artifact containing Brier score, reliability bins, and calibration curves summary.

Confidence Output:
- `confidence_raw` = current internal score.
- `confidence_calibrated` = calibrated probability.

Why enterprise-grade:
- Confidence becomes defensible and testable.
- Calibration quality can be measured and monitored.
- [scikit-learn calibration reference](https://scikit-learn.org/stable/modules/calibration.html)

### C) Governance and Lifecycle Controls
Goal: Align with SR 11-7 expectations for model inventories, validation, and monitoring.

Additions:
- Model Registry artifact: `ta_model_registry`
  - Model name, version, owner, intended use, validation date.
  - Dependencies and key assumptions.
- Validation reports: `ta_validation_report`
  - Conceptual soundness, monitoring metrics, outcomes analysis.
- Annual or quarterly review cycle.

Why enterprise-grade:
- SR 11-7 emphasizes inventories, documentation, validation, and governance controls.
- [Federal Reserve Supervisory Guidance](https://www.federalreserve.gov/frrs/guidance/supervisory-guidance-on-model-risk-management.htm)

## Maintenance Strategy
1. Calibration refresh cadence
- Monthly or quarterly recalibration based on new data.
- Auto-detection of drift triggers early recalibration.

2. Monitoring
- Track hit rate, calibration drift, signal conflict frequency.
- Alert if confidence calibration degrades beyond tolerance.

3. Documentation hygiene
- Versioned documentation updates on each scoring logic change.
- Maintain model inventory with validation status.

This aligns directly with SR 11-7 requirements for ongoing monitoring and governance.
- [Federal Reserve SR 11-7](https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm)

## Expected Dependencies and Cost

### Dependencies
- Optional: `scikit-learn` for calibration and reliability diagnostics.
- Alternative: implement calibration (sigmoid / isotonic) in-house to avoid new heavy dependencies.

### Cost Categories
1. Compute
- Additional walk-forward training for calibration and monitoring.

2. Storage
- New artifacts for scorecards, calibration reports, model registry.

3. Operational overhead
- Governance workflows: documentation updates, validation cadence, and audit reviews.

4. Engineering
- New artifacts and UI components for transparency.

The largest cost is governance discipline rather than runtime expense.

## Suggested Phased Rollout

Phase 1: Explainability Pack
- Implement scorecard artifact and UI breakdown.

Phase 2: Calibration
- Add calibration runtime and confidence calibration metrics.

Phase 3: Governance
- Add model registry and validation reporting.

Phase 4: Monitoring
- Drift detection and automated alerts.

## Summary
This upgrade path is enterprise-grade because it delivers:
- Transparent, auditable decision logic.
- Confidence that is statistically calibrated and monitored.
- Governance and lifecycle controls aligned with SR 11-7 / OCC guidance.

It does not require a total rewrite and can be incrementally layered onto your existing architecture.
