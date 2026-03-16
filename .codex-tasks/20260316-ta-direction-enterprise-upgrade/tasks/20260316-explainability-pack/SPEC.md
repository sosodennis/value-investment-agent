# Task Specification

## Goal

Deliver the Direction Explainability Pack by producing a dedicated direction scorecard artifact and exposing a per-timeframe, per-indicator breakdown in the Technical Analysis UI.

## Non-Goals

- No changes to fundamental agent code.
- No calibration pipeline work (handled in a later subtask).
- No changes to indicator computation logic beyond explainability instrumentation.

## Constraints

- Preserve current agent topology (`application/domain/interface/subdomains`).
- Keep fusion scoring logic consistent; do not change scoring semantics.
- Output contract change must update backend serializer + frontend parser in the same task.
- No compatibility shims.

## Acceptance Criteria

- New artifact kind `ta_direction_scorecard` is saved during fusion compute.
- Technical full report includes `direction_scorecard_id` in `artifact_refs`.
- UI shows per-timeframe + per-indicator contribution breakdown sourced from the new scorecard artifact.
- Validation gates pass.

## Validation

- `rg "direction_scorecard" finance-agent-core/src/agents/technical -n`
- `rg "ta_direction_scorecard" finance-agent-core/src -n`
- `rg "direction_scorecard" frontend/src -n`
