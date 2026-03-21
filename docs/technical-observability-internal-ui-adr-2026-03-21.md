# Technical Observability Internal UI ADR

Date: 2026-03-21
Status: Accepted
Owner: Frontend + Technical Agent Domain

## Decision Summary

We will build `Technical Observability` as a dedicated internal page, not as an extension of the existing technical analysis output panel.

The first implementation will:
- create a separate route at `frontend/src/app/technical-observability/page.tsx`
- consume DB-backed decision observability read models through new backend API endpoints
- present internal governance views for monitoring, event investigation, and calibration readiness

The first implementation will not:
- merge observability into the main analysis workspace at `/`
- productize a public-facing dashboard
- treat artifact-level `observability_summary` as the primary data source for cross-run monitoring

## Context

The current frontend is organized around a single analysis workspace rooted at:
- `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/app/page.tsx`

That page is a live operator workspace with:
- ticker input
- agent roster
- agent detail tabs
- artifact-driven output views

This interaction model is optimized for one analysis session at a time. It is not the right primary surface for:
- multi-event monitoring
- delayed outcome analysis
- cohort aggregation
- calibration dataset readiness review

At the same time, the backend now has a dedicated `decision_observability` capability with:
- `technical_prediction_events`
- `technical_outcome_paths`
- internal monitoring read models
- calibration observation builders

So the UI question is not whether to show these capabilities, but how to expose them without collapsing two different product concerns into one page.

## Drivers

### Product and workflow drivers

- Operators need a stable place to inspect decision quality over time, not only per-run outputs.
- Quant and model-risk workflows need a truth-model view across many events.
- Calibration consumers need readiness and drop-reason visibility before any automated loop exists.

### Architecture drivers

- The current `/` workspace should stay focused on analysis execution.
- DB-backed observability should be consumed through dedicated read contracts, not through ever-growing artifact parsers.
- New UI work should preserve existing route and component cohesion.

### Frontend architecture drivers

- The repo currently uses a single-page workspace pattern plus explicit tabs inside detail panels.
- `frontend/.agent/skills/composition-patterns` argues against boolean-mode sprawl and favors explicit variants and composition.
- `frontend/.agent/skills/react-best-practices` favors clear fetch boundaries and avoiding unnecessary client-side complexity.

## Decision

### 1. Page placement

Create a separate internal page:
- `/technical-observability`

This page is a sibling route to the current workspace, not a tab inside:
- `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/app/page.tsx`

### 2. Audience and scope

This page is internal-only and intended for:
- quant research
- technical ops
- model-risk or governance users

It is not part of the end-user technical analysis experience.

### 3. Data source strategy

The page must read from DB-backed observability read models through explicit backend API routes.

It must not use:
- manual JSON files
- artifact-level `observability_summary` as the main source of truth

Artifact references may still be used as drill-down links for event investigation.

### 4. Information architecture

The page will use one shared filter bar and four explicit views:
- `Overview`
- `Event Explorer`
- `Cohort Analysis`
- `Calibration Readiness`

These are explicit page tabs or sections, not boolean modes on one mega-component.

### 5. Raw vs approved label lens

The UI must clearly separate:
- raw outcomes
- approved label snapshots

This distinction must exist in both naming and controls. The interface must not collapse them into one generic “accuracy” surface.

### 6. Backend boundary

We will add dedicated API endpoints for observability UI consumption from:
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/api/server.py`

These endpoints will adapt data from the existing `decision_observability` runtime and interface contracts. The UI will not reach into repositories or SQL semantics directly.

### 7. Frontend composition strategy

The new page will use:
- a route shell
- a shared filter workspace
- explicit tab components
- a dedicated hook for observability fetching

We explicitly reject:
- extending `TechnicalAnalysisOutput` to act as a monitoring dashboard
- adding a large number of mode props to existing page-level components

## Detailed Architectural Shape

### Frontend route layout

Recommended page structure:
- `app/technical-observability/page.tsx`
- `components/technical-observability/TechnicalObservabilityWorkspace.tsx`
- `components/technical-observability/ObservabilityFilterBar.tsx`
- `components/technical-observability/ObservabilityOverviewTab.tsx`
- `components/technical-observability/ObservabilityEventExplorerTab.tsx`
- `components/technical-observability/ObservabilityCohortTab.tsx`
- `components/technical-observability/ObservabilityCalibrationTab.tsx`
- `components/technical-observability/ObservabilityEventDetailDrawer.tsx`

### Frontend state and fetch ownership

- route page owns metadata and shell setup
- workspace owns shared filter state
- tab components own presentation only
- fetch logic lives in a dedicated hook such as `useTechnicalObservability`

### Backend route ownership

Backend API must expose separate responses for:
- summary and aggregate cards
- paginated event rows
- single event detail
- calibration readiness summaries

These responses should be backed by subdomain interface DTOs, not ORM models.

## Consequences

### Positive

- Keeps the main analysis workspace focused and easier to evolve.
- Gives observability a stable internal home without productizing too early.
- Aligns UI ownership with the existing backend truth model.
- Makes later embedding of a small summary card into the main UI possible without forcing it now.

### Negative

- Adds a second major route to a frontend that is currently centered on one workspace.
- Requires new API boundary work before the page can be implemented cleanly.
- Introduces duplicated shell concerns unless the header/navigation is lightly refactored.

### Neutral but important

- `TechnicalAnalysisOutput` still keeps per-run `observability_summary`, but that remains local run context.
- The new page becomes the main cross-run observability surface.

## Rejected Alternatives

### 1. Add observability as another tab inside the existing agent detail panel

Rejected because:
- the detail panel is scoped to one selected agent in one session
- observability is cross-session and cross-event by design
- this would overload the current page state model

### 2. Extend `TechnicalAnalysisOutput` into a monitoring dashboard

Rejected because:
- that component is artifact-centric
- it would blur report rendering with monitoring consumption
- it would turn the artifact parser path into an accidental analytics platform

### 3. Build a public dashboard first

Rejected because:
- the semantics are still stabilizing
- the intended first consumers are internal
- governance and monitoring needs come before product packaging

## Rollout Guidance

Implementation should proceed in four phases:

1. Backend API contracts and observability routes
2. Frontend route shell, navigation entry, and shared filter workspace
3. Overview and Event Explorer tabs
4. Cohort Analysis and Calibration Readiness tabs

Parallelism is acceptable after shared route and filter contracts stabilize, but only if write scopes stay disjoint.

## Done-When

- `/technical-observability` exists as a dedicated route
- the page reads backend observability APIs rather than artifact JSON truth
- raw outcomes and approved labels are clearly separated in the UI
- event-level drill-down is available
- calibration readiness is visible without implementing automated recalibration

## Follow-Up

This ADR intentionally does not decide:
- whether to embed a future summary card back into the main analysis workspace
- whether to add CSV export in the first release
- whether to add auth/RBAC changes for internal-only page visibility

Those should be handled by implementation follow-ups once this page exists and usage patterns are visible.
