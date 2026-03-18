# T32 Specification

## Goal
Build a normalized deterministic evidence layer in root `application` and migrate semantic projection/setup consumers to reuse it instead of re-deriving evidence in multiple places.

## Slice 1 Scope
- Add an internal evidence bundle contract.
- Build the evidence bundle once from `feature/pattern/regime/fusion/scorecard` artifacts.
- Reuse the bundle for:
  - semantic setup context
  - projection context used by finalize/full report
- Do not change external artifact/report schema in this slice.

## Non-Goals
- Do not introduce policy alerts.
- Do not add frontend rendering changes yet.
- Do not move deterministic calculation ownership out of existing subdomains.
