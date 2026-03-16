# Epic Specification

## Goal

- Deliver enterprise-grade Direction transparency, calibrated confidence, and governance controls for the Technical Analysis system.
- Align the technical calibration pipeline contract with the existing fundamental forward-signal calibration pattern before implementation.

## Non-Goals

- No full rewrite of the technical pipeline.
- No replacement of existing indicators or data providers.
- No UI redesign outside of Direction transparency and confidence labeling.

## Constraints

- Preserve current agent topology: root `application/domain/interface/subdomains`.
- No compatibility shims or legacy dual-writes unless explicitly approved.
- Heavy computation must stay offline; runtime path must remain low-latency.
- LLM remains interpretive only, with deterministic guardrails.
- Align contracts and naming with fundamental calibration pipeline before new technical pipeline work.

## Risk Assessment

- Offline calibration pipeline introduces new operational complexity.
- Confidence calibration requires labeled outcomes and careful data alignment.
- Governance artifacts may add maintenance overhead if not automated.

## Child Deliverables

- Explainability Pack (direction scorecard artifact + UI breakdown).
- Offline Calibration Pipeline (fit + store calibration params).
- Runtime Confidence Integration (calibrated confidence in report + UI).
- Deterministic LLM Guardrail (sentiment alignment with direction).
- Governance + Monitoring Artifacts (registry, validation, drift checks).

## Dependency Notes

- Calibration pipeline depends on explainability scorecard schema.
- Runtime confidence integration depends on calibration outputs.
- Governance/monitoring depends on stable calibration outputs.

## Child Task Types

- `single-full`

## Done-When

- [ ] Every row in `SUBTASKS.csv` is `DONE`
- [ ] Final epic validation passes
