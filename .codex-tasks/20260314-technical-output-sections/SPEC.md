# Task Specification

> Scope anchor for the task. Update only when goals or constraints change, and log the reason in PROGRESS.md.

## Task Shape
<!-- single-compact | single-full | epic | batch -->

- **Shape**: `single-full`

## Goals
<!-- What are we building? Be specific and concrete. -->

- Restructure Technical Output into four sections: Overview, Classic Indicators, Fracdiff Indicators, Other.
- Keep Overview focused on fusion summary + key indicator snapshots.
- Split Other into two internal subsections: Alerts, Verification & Baseline.

## Non-Goals
<!-- What are we explicitly NOT doing? Prevents scope creep. -->

- No backend data or artifact schema changes.
- No new indicators or calculations.
- No new charting libraries or crosshair behavior changes.

## Constraints
<!-- Tech stack, style guide, performance limits, compatibility requirements -->

- Frontend-only change in TechnicalAnalysisOutput.
- Maintain existing toggle behavior (alerts/verification) and layout mode options.
- Reuse existing data already in the Technical output artifacts.

## Environment
<!-- Auto-filled by agent at init time -->

- **Project root**: `/Users/denniswong/Desktop/Project/value-investment-agent`
- **Language/runtime**: TypeScript / React
- **Package manager**: npm
- **Test framework**: tsc
- **Build command**: `cd frontend && npm run typecheck`
- **Existing test count**: N/A (typecheck only)

## Risk Assessment
<!-- Identify potential blockers or unknowns before starting -->

- [ ] External dependencies (APIs, services) — availability confirmed?
- [x] Breaking changes to existing code — impact assessed?
- [ ] Large file generation — disk space sufficient?
- [ ] Long-running tests — timeout configured?

## Deliverables
<!-- Concrete outputs: files, features, endpoints, docs -->

- Updated Technical Output layout with 4 sections and internal sub-sections for Other.

## Done-When
<!-- Final acceptance criteria. The task is DONE when ALL of these pass. -->

- [ ] Overview / Classic / Fracdiff / Other sections render correctly.
- [ ] Alerts + Verification/Baseline are grouped under Other.
- [ ] `npm run typecheck` passes.

## Final Validation Command
<!-- Single command that validates the entire deliverable. Runs at close-out. -->

```bash
cd frontend && npm run typecheck
```

## Demo Flow (optional)
<!-- Step-by-step instructions to demonstrate the finished product. -->

1. Open Technical output for a ticker.
2. Confirm Overview shows Direction/Risk/Confidence + LLM summary + key indicator snapshots.
3. Confirm Classic section shows OHLC and classic indicator charts.
4. Confirm Fracdiff section shows FD chart and related content.
5. Confirm Other contains Alerts + Verification/Baseline panels.
