# Technical Calibrated Confidence Gap Report

Date: 2026-03-18

## Executive Summary

The current Technical `confidence` field is usable as an internal fusion-strength score, but it is not yet suitable to present as a true calibrated probability to end users.

Today, the system already has enough data and metadata to support an enterprise-safe UI/UX improvement:
- rename or reposition the current field as internal signal strength
- surface calibration status, degraded state, and conflict context more explicitly
- avoid presenting raw internal magnitude as a probability-like percentage

However, the current system does not yet have enough outcome-linked data, calibration diagnostics, or lifecycle monitoring to support a defensible enterprise-grade `calibrated confidence` percentage.

This report records the missing capabilities, why they matter, and what must be added before calibrated confidence can be treated as a probability-like user-facing metric.

## Current State

### What the current number is

The current Technical `confidence` is derived from fusion score magnitude and optional statistical strength. It is not currently an empirically validated probability of correctness.

Current behavior:
- fusion produces a directional result and an internal `confidence`
- runtime optionally applies a calibration mapping
- if calibration is not applied, the system falls back to the raw confidence value
- UI can still display the resulting percentage prominently

### What the current number is not

The current field should not be interpreted as:
- probability that price will move in the predicted direction
- trade win rate
- expected return likelihood
- reliability-adjusted confidence under degraded data conditions

### What is already available in the backend

The current backend and report contracts already provide meaningful enterprise context:
- `confidence_raw`
- `confidence_calibrated`
- `confidence_calibration`
- `degraded_reasons`
- `conflict_reasons`
- `quality_summary`
- `observability_summary`
- `evidence_bundle`
- verification context such as baseline status and robustness flags

This is sufficient for UI/UX correction and better semantic presentation.

## Core Gap

The core gap is simple:

We do not yet have enough evidence to claim that a displayed Technical confidence percentage corresponds to real-world hit rate probability.

In enterprise terms, the current output is closer to:
- internal signal strength
- directional score magnitude
- fusion conviction

It is not yet:
- calibrated probability
- empirically validated confidence
- monitored reliability estimate

## What Is Missing Before We Can Offer True Calibrated Confidence

### 1) Explicit Ground-Truth Target Definition

We need a formal definition of what the confidence is supposed to predict.

Examples:
- whether the predicted direction is correct over the next 1 day
- whether a breakout setup succeeds within the next 5 bars
- whether price extends by at least X ATR in the predicted direction within a defined horizon
- whether a neutral/consolidation call remains inside a range for a defined horizon

Without a target definition, calibration has no stable meaning.

Required additions:
- canonical target schema
- explicit horizon definitions
- success/failure labeling rules
- direction-specific target semantics

### 2) Historical Labeled Outcome Dataset

We need replayable historical observations that connect:
- raw fusion score
- direction
- timeframe
- regime
- degraded state
- eventual realized outcome

This is the minimum dataset required to answer questions like:
- when raw confidence was between 0.80 and 0.90, how often was the call actually correct?
- how does degraded data change realized accuracy?
- how does confidence behave across bullish, bearish, and neutral regimes?

Required additions:
- historical calibration observation pipeline
- replayable observation storage
- consistent labeling window
- enough retained samples across market conditions

### 3) Calibration Diagnostics and Quality Metrics

A mapping file alone is not enough. Enterprise-grade confidence needs quantitative evidence that the mapping is working.

Minimum required diagnostics:
- Expected Calibration Error (ECE)
- Brier score
- reliability bins / reliability diagram data
- bucket sample counts
- minimum sample threshold checks
- fallback reason when data is insufficient

Why this matters:
- confidence percentages without calibration diagnostics are not auditable
- product teams cannot tell whether the mapping is valid or stale
- users may over-trust fine-grained percentages that are not empirically grounded

### 4) Segmented Calibration, Not One Global Mapping

Technical signal quality depends materially on context.

Calibration likely needs segmentation by some combination of:
- timeframe
- direction family
- regime type
- degraded vs. full-data path
- conflict-heavy vs. clean confluence
- horizon definition

A single global mapping will likely hide important differences and produce misleading percentages.

Required additions:
- calibration segmentation policy
- sample sufficiency rules by segment
- fallback hierarchy when segment data is thin

### 5) Lifecycle Monitoring and Drift Management

Even a valid calibration fit will drift over time.

Enterprise-grade calibrated confidence requires ongoing monitoring:
- calibration drift
- hit-rate drift
- bucket instability
- degraded-path bias
- regime-specific breakdown
- retraining / refit cadence

Required additions:
- monitoring metrics artifact
- thresholds for refit or rollback
- periodic review cadence
- production diagnostics and alerting

### 6) Direction Vocabulary Alignment

There is also a semantic integration gap in the current technical stack.

The calibration service currently expects normalized directions such as:
- `bullish`
- `bearish`

But fusion produces direction labels such as:
- `BULLISH_EXTENSION`
- `BEARISH_EXTENSION`
- `NEUTRAL_CONSOLIDATION`

This mismatch means calibration may not apply cleanly to current production outputs without a canonical mapping layer.

Required additions:
- canonical direction-to-calibration mapping
- support for neutral-state confidence semantics
- explicit behavior when direction is not calibratable

### 7) Confidence Semantics for Neutral Calls

Neutral states need special treatment.

Examples:
- `NEUTRAL_CONSOLIDATION` is not the same kind of prediction as `BULLISH_EXTENSION`
- users may interpret a percentage on a neutral call differently from a directional breakout call

Required additions:
- neutral-specific target definitions
- neutral calibration rules
- UI semantics that do not imply directional probability when the output is a range/consolidation state

## What We Can Do Now Without New Market Data

We can already make the product materially safer and more enterprise-appropriate without new data sources.

Immediate improvements supported by the current backend:
- treat current displayed percentage as `signal strength`, not calibrated probability
- surface `calibration status`
- surface `degraded data path`
- surface `conflict level`
- derive a user-facing `setup reliability` summary from existing quality and observability signals

This does not require new technical indicators or new market data. It requires:
- clearer contract semantics
- safer UI wording
- deterministic reliability projection

## What Additional Data or Artifacts We Need

The following list summarizes the missing pieces as future implementation inputs.

### Data Inputs
- labeled historical technical outcomes
- explicit horizon definitions
- direction outcome labels
- neutral-state outcome labels
- segmented replay data across regimes and degraded paths

### Derived Artifacts
- technical calibration observations artifact
- calibration fit report artifact
- reliability diagnostics artifact
- production calibration monitoring artifact

### Runtime Metadata
- canonical calibration direction mapping
- calibration eligibility flags
- sample sufficiency status
- calibration freshness / staleness
- fallback reason when calibrated confidence is unavailable

## Recommended Phased Roadmap

### Phase 1: Enterprise-Safe UX Correction

Goal:
- stop presenting raw internal magnitude as if it were a true probability

Actions:
- rename or reposition the current field as `signal strength`
- show calibration status explicitly
- add reliability-oriented summaries using existing `quality_summary`, `observability_summary`, and conflict/degraded signals

Dependency level:
- available now

### Phase 2: Calibration Observation Pipeline

Goal:
- build the data foundation for real calibrated confidence

Actions:
- define target outcomes and horizons
- generate historical observations from replay
- store calibration observation artifacts

Dependency level:
- requires new offline data pipeline work

### Phase 3: Calibration Fit and Diagnostics

Goal:
- fit and validate calibration mappings

Actions:
- fit segmented mappings
- compute ECE, Brier, and bucket diagnostics
- define fallback policy for insufficient samples

Dependency level:
- requires Phase 2

### Phase 4: Productionized Calibrated Confidence

Goal:
- expose calibrated confidence only when it is valid and auditable

Actions:
- ship calibrated confidence behind eligibility gates
- display `confidence %` only when calibration is applied and healthy
- fall back to `signal strength` otherwise

Dependency level:
- requires Phase 3

### Phase 5: Monitoring and Governance

Goal:
- keep calibrated confidence trustworthy over time

Actions:
- add drift monitoring
- define refit cadence
- create validation review and rollback criteria

Dependency level:
- requires Phase 4

## Decision Guidance

### What we should do now

We should not wait for a full calibration system before fixing the product semantics.

Immediate recommendation:
- do the UX/contract correction now
- do not market the current number as calibrated confidence

### What we should not claim yet

We should not yet claim that Technical confidence:
- is a probability of success
- is empirically calibrated
- is reliability-adjusted under degraded conditions
- is suitable for enterprise probability interpretation

## Summary

The system is already strong enough to support better enterprise-safe presentation today, but it is not yet ready to support a true calibrated confidence percentage.

To get there, we still need:
1. explicit target definitions
2. labeled historical outcome data
3. calibration diagnostics
4. segmented calibration policy
5. drift monitoring
6. direction vocabulary alignment
7. neutral-state confidence semantics

Until those are in place, the correct product posture is:
- use the current field as internal signal strength
- expose calibration and reliability context
- reserve true percentage confidence for future calibrated rollout
