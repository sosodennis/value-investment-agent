# Task Specification

> Scope anchor for the task. Update only when goals or constraints change, and log the reason in PROGRESS.md.

## Task Shape
<!-- single-compact | single-full | epic | batch -->

- **Shape**: single-full

## Goals
<!-- What are we building? Be specific and concrete. -->

- Add enterprise-grade `momentum_extremes` output to the technical report payload.
- Place FD Z-Score in Momentum & Extremes layer and surface it in UI Trade Brief, Setup Evidence, and Diagnostics.
- Keep thresholds consistent with existing fusion/alert logic and avoid new data sources.

## Non-Goals
<!-- What are we explicitly NOT doing? Prevents scope creep. -->

- No changes to FD Z-Score calculation or signal fusion algorithm.
- No new market data providers or additional indicators.
- No chart layout redesign beyond the Momentum & Extremes panels.

## Constraints
<!-- Tech stack, style guide, performance limits, compatibility requirements -->

- Pydantic v2 conventions (use model_dump, no dict()).
- Breaking changes are allowed (no compatibility shims).
- Keep UI styling consistent with current Technical Intelligence layout.

## Environment
<!-- Auto-filled by agent at init time -->

- **Project root**: /Users/denniswong/Desktop/Project/value-investment-agent
- **Language/runtime**: Python + TypeScript (React)
- **Package manager**: uv (backend), npm (frontend)
- **Test framework**: pytest (backend), n/a (frontend)
- **Build command**: n/a
- **Existing test count**: n/a

## Risk Assessment
<!-- Identify potential blockers or unknowns before starting -->

- [ ] External dependencies (APIs, services) — availability confirmed?
- [x] Breaking changes to existing code — impact assessed?
- [ ] Large file generation — disk space sufficient?
- [ ] Long-running tests — timeout configured?

## Deliverables
<!-- Concrete outputs: files, features, endpoints, docs -->

- `momentum_extremes` added to technical report schema and payload.
- UI sections show FD Z-Score in Trade Brief, Setup Evidence, Diagnostics.
- Updated generated types or manual type updates for frontend consumption.

## Done-When
<!-- Final acceptance criteria. The task is DONE when ALL of these pass. -->

- [ ] Technical report payload includes `momentum_extremes` with FD Z-Score data.
- [ ] UI renders Momentum & Extremes content in the three required sections.
- [ ] Validation command completes or is explicitly skipped with reason logged.

## Final Validation Command
<!-- Single command that validates the entire deliverable. Runs at close-out. -->

```bash
uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical finance-agent-core/src/interface
```

## Demo Flow (optional)
<!-- Step-by-step instructions to demonstrate the finished product. -->

1. Run a technical analysis for a ticker with indicator series available.
2. Open Technical Intelligence output and confirm Momentum & Extremes presence in Trade Brief, Setup Evidence, Diagnostics.
