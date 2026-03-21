# Epic Specification

## Goal

- Implement the internal `Technical Observability` UI described in `/Users/denniswong/Desktop/Project/value-investment-agent/docs/technical-observability-internal-ui-adr-2026-03-21.md` across backend read APIs, frontend routing, filter state, monitoring views, and calibration-readiness presentation.

## Non-Goals

- Merge observability into the main analysis workspace at `/`.
- Productize a public-facing dashboard.
- Replace the existing technical artifact output experience.
- Build automated recalibration loops.

## Constraints

- Keep observability as a dedicated route at `/technical-observability`.
- Use DB-backed observability read models as the primary truth source.
- Keep `raw outcomes` and `approved label snapshots` visibly distinct.
- Avoid boolean-mode sprawl in existing frontend components.
- Follow existing repo architecture boundaries and strict typing.

## Risk Assessment

- Weak API contracts can force frontend rework or leak backend storage semantics.
- Mixing observability into the current workspace can regress the analysis UX.
- Overly broad filter state can create brittle component coupling and unclear defaults.
- Large dashboard-style pages can become unreadable if tabs and drill-downs are not explicit.

## Child Deliverables

- Phase 1 backend observability UI API contracts and routes
- Phase 2 frontend route shell navigation and shared filter workspace
- Phase 3 overview and event explorer views
- Phase 4 cohort analysis and calibration readiness views

## Dependency Notes

- Child 2 depends on child 1 because the route shell and hooks need stable API contracts.
- Child 3 depends on child 2 because overview and explorer should sit on the shared route shell and filter workspace.
- Child 4 depends on child 2 because cohort and calibration views use the same shared filters and page shell; it may proceed in parallel with child 3 if file ownership stays disjoint.

## Child Task Types

- `single-compact`
- `single-full`
- `batch`

## Done-When

- [ ] Every row in `SUBTASKS.csv` is `DONE`
- [ ] The implementation satisfies the ADR success criteria
- [ ] Validation gates for each phase have explicit passing evidence
