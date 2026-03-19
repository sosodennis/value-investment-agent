# RFC: Calibration Upgrade Roadmap, Complexity, and ROI

Date: 2026-03-18
Status: Supporting Annex
Owner: Codex working notes for future implementation planning

## Document Role

This file is a **supporting annex** to the master roadmap:

- [technical-strategy-master-roadmap.md](/Users/denniswong/Desktop/Project/value-investment-agent/docs/rfc/technical-strategy-master-roadmap.md)

Primary purpose:

- explain calibration concepts, maturity, upgrade paths, complexity, and ROI.

Dependency note:

- this RFC should be read **after** the master roadmap,
- and **after** the technical quant feature roadmap,
- because calibration strategy depends on the semantics of the signals and features the technical system decides to produce.

Read order:

1. [technical-strategy-master-roadmap.md](/Users/denniswong/Desktop/Project/value-investment-agent/docs/rfc/technical-strategy-master-roadmap.md)
2. [technical-quant-feature-priorities-free-data.md](/Users/denniswong/Desktop/Project/value-investment-agent/docs/rfc/technical-quant-feature-priorities-free-data.md)
3. [calibration-upgrade-roadmap-and-roi.md](/Users/denniswong/Desktop/Project/value-investment-agent/docs/rfc/calibration-upgrade-roadmap-and-roi.md)

## Summary

This RFC records a pragmatic upgrade path for calibration in the project, with a focus on:

- what "enterprise-like" calibration should mean in this codebase,
- how calibration data should be collected in an AI-agents architecture,
- why technical and fundamental calibration should not be treated as the same problem,
- what should be built first,
- and the expected complexity and ROI.

The main recommendation is:

- do not jump directly to full enterprise-grade calibration for both domains,
- build a versioned prediction-event and outcome-labeling loop first,
- prioritize `technical` calibration before `fundamental`,
- treat `fundamental` as a slower, more governance-heavy calibration track.

## Background

The project already contains two different calibration families:

### Technical

Technical calibration is primarily a score-to-confidence style calibration.

Current local implementation:

- [`technical_direction_calibration_service.py`](/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/technical/subdomains/calibration/domain/policies/technical_direction_calibration_service.py)
- [`run_fusion_compute_use_case.py`](/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/technical/application/use_cases/run_fusion_compute_use_case.py)
- [`fitting_service.py`](/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/technical/subdomains/calibration/domain/fitting_service.py)

What it tries to answer:

- given a raw technical direction score, how much confidence should be associated with it?

### Fundamental

Fundamental calibration is primarily an impact or parameter-adjustment calibration.

Current local implementation:

- [`forward_signal_calibration_service.py`](/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/subdomains/forward_signals/domain/policies/forward_signal_calibration_service.py)
- [`forward_signal_adjustment_service.py`](/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/subdomains/core_valuation/domain/parameterization/forward_signal_adjustment_service.py)
- [`dataset_builder_service.py`](/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/subdomains/forward_signals/domain/calibration/dataset_builder_service.py)

What it tries to answer:

- given a raw forward signal, how much should valuation assumptions be adjusted in basis points?

These two calibrations should not be unified into a single methodology.

## What Enterprise-Grade Calibration Usually Means

In enterprise systems, calibration is usually not just a mapping function. It is a governed lifecycle:

1. Define what the calibrated output is supposed to mean.
2. Log runtime prediction events with version metadata.
3. Wait for delayed ground truth or proxy outcomes.
4. Join predictions with outcomes into a calibration dataset.
5. Fit a candidate calibration mapping offline.
6. Validate it with explicit metrics and sample thresholds.
7. Publish a versioned mapping artifact.
8. Monitor drift and retire or refit when needed.

For this project, the most important design rule is:

- runtime should collect prediction evidence,
- offline jobs should build datasets and fit calibration,
- production inference should only read published calibration artifacts.

## Why This Matters for an AI-Agents System

Because this is an AI-agents system, calibration complexity is higher than in a single static model.

Prediction semantics can change when any of the following changes:

- prompt or extraction behavior,
- tool behavior,
- fusion policy,
- rule thresholds,
- feature engineering,
- valuation parameterization,
- direction or target definitions.

This means calibration data must be version-aware.

Ground truth does not become invalid after a model change. What becomes invalid is mixing old prediction semantics with new prediction semantics as if they were equivalent.

## Recommended Collection Architecture

The recommended architecture is a hybrid loop:

1. Runtime prediction event capture
2. Delayed outcome labeling
3. Offline calibration dataset build
4. Offline fitting and validation
5. Published mapping artifact

### Core principle

Store three separate layers:

1. Ground truth layer
- realized market or business outcome
- remains valid over time

2. Prediction event layer
- what the system predicted at the time
- strongly versioned

3. Calibration dataset layer
- derived by joining prediction events with ground truth
- version-aware and rebuildable

This is the safest pattern for future changes.

## Recommended Runtime Collection

### Technical prediction events

Each technical run should log a prediction event with at least:

- `prediction_id`
- `run_id` or `trace_id`
- `ticker`
- `as_of_timestamp`
- `primary_timeframe`
- `target_horizon`
- `direction`
- `overall_score`
- `signal_strength_raw`
- `signal_strength_effective`
- `confidence_calibrated`
- `confidence_eligibility`
- `degraded_reasons`
- `conflict_reasons`
- `feature/fusion/report artifact ids`
- `model/policy/schema version fields`

### Fundamental prediction events

Each fundamental run should log a prediction event with at least:

- `prediction_id`
- `run_id` or `trace_id`
- `ticker`
- `as_of_timestamp`
- `model_type`
- `current_price`
- `intrinsic_value`
- `valuation_gap`
- `raw_growth_adjustment_basis_points`
- `raw_margin_adjustment_basis_points`
- `calibrated_growth_adjustment_basis_points`
- `calibrated_margin_adjustment_basis_points`
- `forward_signal_summary`
- `source_types`
- `market snapshot quality`
- `assumption and degraded flags`
- `policy/schema version fields`

## Recommended Outcome Labeling

### Technical

Technical should be the first calibration track to upgrade because the label problem is cleaner.

Suggested labels:

- realized return at `T+1d`, `T+5d`, `T+1wk`
- realized direction sign
- hit/miss for predicted direction
- optional excursion metrics such as max drawdown or max favorable excursion

Suggested approach:

- daily or hourly job finds matured prediction events,
- fetches realized price path,
- writes a labeled outcome record,
- later joins into calibration observations.

### Fundamental

Fundamental should use a staged approach.

#### Near-term

Continue to use replay and anchor-target style calibration for forward-signal adjustments.

#### Mid-term

Add delayed proxy outcomes such as:

- future 90d, 180d, 365d price paths,
- estimate revision direction,
- revenue or margin realization trend where available.

#### Caution

Fundamental labels are harder because price is not a perfect proxy for valuation-assumption correctness.

## Versioning Strategy

Every prediction event should carry version metadata sufficient to determine whether it can be used with a future calibration dataset.

Recommended minimum:

- `agent_version`
- `policy_version`
- `schema_version`
- `calibration_mapping_version`
- `prompt_version` where applicable
- `feature_contract_version`
- `target_definition_version`

### Practical rule

Small display-only changes:

- can usually keep using existing calibration data

Medium semantic changes:

- keep old data,
- but build new calibration datasets separately by generation or version family

Large meaning changes:

- old prediction events remain useful for historical benchmarking,
- but should not be mixed into the fit set for the new semantics

## Current Maturity Assessment

The current calibration state is not "wrong" or "useless."

It is better understood as:

- already useful,
- already structured enough to support controlled evolution,
- but not yet a full enterprise calibration program.

### Technical calibration maturity

| Dimension | Current State | Maturity | Notes |
|---|---|---|---|
| Calibration objective clarity | Reasonably clear | Medium-High | It is mostly a direction score to confidence style calibration. |
| Runtime integration | Implemented | Medium-High | Calibration is wired into the fusion/report path and now also coexists with signal-strength semantics. |
| Versioning and fallback | Present | Medium-High | Mapping versions, defaults, and fallback behavior already exist. |
| Dataset structure | Present | Medium | There is a dedicated observation contract and fitting service. |
| Ground-truth quality | Partial | Medium | Outcome definition is straightforward, but the production labeling loop is not yet mature. |
| Validation metrics | Limited | Low-Medium | There is fitting logic, but no formal ECE/Brier/reliability artifact program yet. |
| Drift monitoring | Limited | Low | No mature continuous calibration monitoring loop yet. |
| Consumer safety | Improving | Medium | Backend semantics and UI safety work have reduced misuse risk, but the long-term confidence program is still incomplete. |

Technical overall maturity:

- `Current rating: 6.5/10`
- `Practical label: enterprise-like intermediate calibration`

Why this rating:

- the shape of the system is good,
- the target problem is relatively clean,
- but it still lacks the full prediction-to-outcome feedback and monitoring loop expected in a mature enterprise program.

### Fundamental calibration maturity

| Dimension | Current State | Maturity | Notes |
|---|---|---|---|
| Calibration objective clarity | Clear enough for current use | Medium | It is an adjustment-impact calibration, not a probability calibration. |
| Runtime integration | Implemented | High | It already affects valuation assumptions in a controlled way. |
| Versioning and fallback | Present | Medium-High | Mapping version and fallback/default handling already exist. |
| Dataset structure | Present | Medium | There is a defined dataset builder and fitting service. |
| Ground-truth quality | Proxy-based | Low-Medium | Current target construction is useful, but still relies on anchor and replay proxies rather than clean realized truth. |
| Validation metrics | Limited | Low-Medium | There is fit structure, but not a strong formal monitoring program. |
| Drift monitoring | Limited | Low | No mature ongoing monitoring loop yet. |
| Business usefulness today | Strong | High | Even without full enterprise-grade calibration, it already acts as a valuable governed adjustment layer. |

Fundamental overall maturity:

- `Current rating: 6.0/10`
- `Practical label: enterprise-style governed adjustment calibration`

Why this rating:

- it is already useful in production semantics,
- but its target and label problem is materially harder,
- so it is farther away from a rigorously validated enterprise calibration program than the technical track.

### Side-by-side interpretation

| Track | Current Value Today | Biggest Strength | Biggest Gap |
|---|---|---|---|
| Technical | Medium-High | clearer label problem and better path to empirical validation | lacks full data collection, monitoring, and validation metrics |
| Fundamental | High for internal policy use | directly improves valuation assumption governance | proxy-based target construction is harder to defend as full calibration |

Recommended interpretation:

- `technical` is closer to a future full calibration program,
- `fundamental` is already useful today, but should be treated as a governed adjustment system first and a deeper calibration program second.

## Mid-Term Upgrade Recommendation

### Priority 1: Technical calibration pipeline

Build a governed technical calibration loop first.

Recommended components:

1. runtime `technical_prediction_event`
2. outcome labeling job
3. calibration observation builder
4. offline fit job
5. fit report artifact
6. published mapping artifact
7. monitoring summary

Why first:

- labels are more objective,
- existing technical calibration already resembles confidence calibration,
- user-facing value is immediate,
- ROI is higher than fundamental at this stage.

### Priority 2: Fundamental calibration hardening

Do not immediately pursue probability-like calibration for fundamental.

Recommended focus:

- richer prediction event capture,
- cleaner versioning,
- stronger replay-grounded adjustment datasets,
- source and metric stability analysis,
- better proxy-based validation before deeper statistical calibration.

## Complexity Assessment

### High-level complexity

| Track | Engineering Complexity | Data Semantics Complexity | Ongoing Maintenance |
|---|---|---:|---:|
| Technical runtime event logging | Medium | Low-Medium | Medium |
| Technical delayed outcome labeling | Medium | Medium | Medium |
| Technical offline fitting and monitoring | Medium-High | Medium | Medium-High |
| Fundamental runtime event logging | Medium | Medium | Medium |
| Fundamental delayed outcome labeling | High | High | High |
| Fundamental full calibration program | High-Very High | Very High | Very High |

### Why technical is easier

- target labels are clearer,
- horizons are easier to define,
- score-to-outcome mapping is more standard,
- calibration metrics are more conventional.

### Why fundamental is harder

- the target is less obvious,
- price is an imperfect label,
- valuation assumptions are multi-step and model-dependent,
- different model types may need different calibration semantics.

## ROI Assessment

### Technical calibration upgrade

| Area | Expected ROI | Why |
|---|---|---|
| Prediction event logging | High | foundation for all later validation and monitoring |
| Outcome labeling | High | enables real empirical evaluation |
| Offline fit and versioning | High | improves trust and governance |
| Drift monitoring | Medium-High | prevents stale mappings from silently degrading |
| Full calibrated probability UX | Medium | useful, but only after the data and governance foundation exists |

### Fundamental calibration upgrade

| Area | Expected ROI | Why |
|---|---|---|
| Richer event logging | High | low regret and useful regardless of later calibration depth |
| Replay-grounded adjustment analysis | Medium-High | helps refine existing adjustment policy |
| Delayed proxy outcome labeling | Medium | useful, but interpretation remains noisy |
| Full statistical calibration program | Low-Medium in near term | expensive and semantically harder to defend |

## Recommendation by Phase

### Phase 1

Build the shared calibration data backbone:

- prediction event schemas
- version metadata
- storage and artifact references

Focus first on technical.

### Phase 2

Add technical delayed labeling and offline fit jobs:

- horizon-aware outcome join
- fit report artifact
- mapping publish flow
- monitoring summary

### Phase 3

Strengthen technical governance:

- validation metrics
- re-fit triggers
- drift checks
- release gates for mapping updates

### Phase 4

Extend the same backbone to fundamental:

- richer forward-signal event logs
- replay-based calibration dataset improvements
- limited proxy-outcome monitoring

### Phase 5

Only if justified by product value, move toward more advanced fundamental calibration.

## What Should Not Be Done Yet

The following are not recommended as immediate next steps:

- full enterprise-grade calibration for both domains at the same time
- treating technical and fundamental as one calibration problem
- runtime online re-fitting during user requests
- showing probability-like calibrated confidence in UI before the data and validation loop is mature

## Final Recommendation

The best next move is not "upgrade everything."

The best next move is:

1. build a versioned prediction-event backbone,
2. implement technical delayed outcome labeling,
3. run offline technical calibration first,
4. use that experience to decide how far fundamental calibration should go.

This keeps system complexity under control while still moving the project in an enterprise direction.
