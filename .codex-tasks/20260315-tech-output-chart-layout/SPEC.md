# Task Specification

> Scope anchor for the task. Update only when goals or constraints change, and log the reason in PROGRESS.md.

## Task Shape
<!-- single-compact | single-full | epic | batch -->

- **Shape**: `single-full`

## Goals
<!-- What are we building? Be specific and concrete. -->

- Remove all Show/Hide chart controls and messages so chart sections are always visible.
- Always fetch and render chart artifacts when IDs are present (no `showAdvanced` gating).
- Place `Classic Indicator Panels` and `Fracdiff Panel` on the same row for desktop, stacking on smaller screens.

## Non-Goals
<!-- What are we explicitly NOT doing? Prevents scope creep. -->

- No backend or artifact schema changes.
- No new indicators, computations, or chart libraries.
- No visual redesign outside the Classic/Fracdiff panel layout change.

## Constraints
<!-- Tech stack, style guide, performance limits, compatibility requirements -->

- Use existing React/Next/Tailwind patterns in the file.
- Preserve current chart sync/zoom behavior.
- Keep graceful empty/error states for missing artifacts.

## Environment
<!-- Auto-filled by agent at init time -->

- **Project root**: `/Users/denniswong/Desktop/Project/value-investment-agent`
- **Language/runtime**: `TypeScript / React (Next.js)`
- **Package manager**: `npm` (scripts in `frontend/package.json`)
- **Test framework**: `vitest`
- **Build command**: `cd frontend && npm run build`
- **Existing test count**: `<auto>`

## Risk Assessment
<!-- Identify potential blockers or unknowns before starting -->

- [ ] External dependencies (APIs, services) — availability confirmed?
- [ ] Breaking changes to existing code — impact assessed?
- [ ] Large file generation — disk space sufficient?
- [ ] Long-running tests — timeout configured?

## Deliverables
<!-- Concrete outputs: files, features, endpoints, docs -->

- Updated UI logic in `frontend/src/components/agent-outputs/TechnicalAnalysisOutput.tsx` to always show charts and align Classic + Fracdiff panels in one row.

## Done-When
<!-- Final acceptance criteria. The task is DONE when ALL of these pass. -->

- [ ] No Show/Hide chart buttons or “Enable charts” helper text remain in `TechnicalAnalysisOutput`.
- [ ] Chart artifacts are fetched without `showAdvanced` gating.
- [ ] Classic and Fracdiff panels render in a shared row on desktop and stack on mobile.

## Final Validation Command
<!-- Single command that validates the entire deliverable. Runs at close-out. -->

```bash
cd frontend && npm run typecheck
```

## Demo Flow (optional)
<!-- Step-by-step instructions to demonstrate the finished product. -->

1. Open a Technical Analysis output page with chart artifacts.
2. Confirm charts are always visible with no Show/Hide buttons.
3. Confirm Classic and Fracdiff panels share a row on desktop and stack on smaller widths.
