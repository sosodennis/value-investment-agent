# Task Specification

> Scope anchor for the task. Update only when goals or constraints change, and log the reason in PROGRESS.md.

## Task Shape
<!-- single-compact | single-full | epic | batch -->

- **Shape**: `single-full`

## Goals
<!-- What are we building? Be specific and concrete. -->

- Define enterprise-grade indicator layout rules (default + optional toggles) based on validated industry practices.
- Remove duplicate chart sections and streamline UI content in the Technical Analysis output.
- Implement layout toggles to control indicator panes (split / combined / summary).

## Non-Goals
<!-- What are we explicitly NOT doing? Prevents scope creep. -->

- No backend data changes or new indicator calculations.
- No new charting library adoption.
- No changes to alert logic or data models.

## Constraints
<!-- Tech stack, style guide, performance limits, compatibility requirements -->

- Frontend-only changes (React + lightweight-charts + recharts existing stack).
- Preserve crosshair sync behavior.
- Keep UI simple and avoid information overload.
- Must include web-validated rationale in plan notes.

## Environment
<!-- Auto-filled by agent at init time -->

- **Project root**: `/Users/denniswong/Desktop/Project/value-investment-agent`
- **Language/runtime**: TypeScript / React
- **Package manager**: npm
- **Test framework**: tsc (typecheck)
- **Build command**: `npm run typecheck` (from `frontend/`)
- **Existing test count**: N/A (typecheck only)

## Risk Assessment
<!-- Identify potential blockers or unknowns before starting -->

- [ ] External dependencies (APIs, services) — availability confirmed?
- [x] Breaking changes to existing code — impact assessed?
- [ ] Large file generation — disk space sufficient?
- [ ] Long-running tests — timeout configured?

## Deliverables
<!-- Concrete outputs: files, features, endpoints, docs -->

- Updated Technical Analysis UI layout rules and toggles.
- Removal of duplicate FracDiff chart section.
- Updated documentation/comments where needed.

## Done-When
<!-- Final acceptance criteria. The task is DONE when ALL of these pass. -->

- [ ] User can switch between split/combined/summary indicator layouts.
- [ ] Duplicate FracDiff chart removed without loss of key signals.
- [ ] Crosshair sync remains stable.
- [ ] `npm run typecheck` passes.

## Final Validation Command
<!-- Single command that validates the entire deliverable. Runs at close-out. -->

```bash
cd frontend && npm run typecheck
```

## Demo Flow (optional)
<!-- Step-by-step instructions to demonstrate the finished product. -->

1. Open Technical Analysis output.
2. Switch indicator layout modes and verify pane changes.
3. Confirm no duplicate FracDiff chart remains.
4. Hover/zoom to verify crosshair stability.
