# Task Specification

## Goal

Integrate calibrated confidence into the Technical Analysis runtime output by loading the technical calibration mapping at runtime, applying it to fusion scores, and exposing both raw and calibrated confidence (plus calibration source metadata) in the report payload and UI.

## Non-Goals

- No new calibration fitting logic (offline pipeline already delivered).
- No changes to fundamental agent code.
- No UI redesign beyond confidence display and calibration metadata.

## Constraints

- Preserve current agent topology (`application/domain/interface/subdomains`).
- Output contract changes must update backend serializers + frontend parsers in the same task.
- No compatibility shims or legacy dual writes.
- Runtime path must remain low latency.

## Acceptance Criteria

- Technical fusion report includes `confidence_raw`, `confidence_calibrated`, and `confidence_calibration` metadata.
- Technical full report exposes calibrated confidence and calibration source tag.
- Runtime loads calibration mapping via env override and falls back to embedded defaults with degraded metadata.
- UI displays calibrated confidence and indicates calibration source.
- Validation gates pass.

## Validation

- `rg "confidence_calibrated" finance-agent-core/src/agents/technical -n`
- `rg "confidence_calibration" finance-agent-core/src -n`
- `rg "confidence_calibrated" frontend/src -n`
