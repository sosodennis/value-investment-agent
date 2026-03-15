# Task Specification

> Scope anchor for the task. Update only when goals or constraints change, and log the reason in PROGRESS.md.

## Task Shape
<!-- single-compact | single-full | epic | batch -->

- **Shape**: `single-full`

## Goals
<!-- What are we building? Be specific and concrete. -->

- Build a multi-pane technical chart layout matching the provided reference (Price + MA/BB overlays, then Volume/RSI/MACD/Fracdiff panes).
- Implement a synchronized floating tooltip that follows crosshair and aggregates OHLC + indicator values, with transparency.
- Keep crosshair/time-range sync across all panes.

## Non-Goals
<!-- What are we explicitly NOT doing? Prevents scope creep. -->

- No chart library changes.
- No rework of unrelated UI sections.
- No backend schema changes beyond indicator series extensions needed for overlays.

## Constraints
<!-- Tech stack, style guide, performance limits, compatibility requirements -->

- Use existing lightweight-charts integration and sync utilities.
- Tooltip must be HTML overlay (per official lightweight-charts guidance).
- Prefer minimal, reversible changes.

## Environment
<!-- Auto-filled by agent at init time -->

- **Project root**: `/Users/denniswong/Desktop/Project/value-investment-agent`
- **Language/runtime**: `TypeScript / React (Next.js) + Python`
- **Package manager**: `npm` (frontend) / `uv` (backend)
- **Test framework**: `vitest` / `pytest`
- **Build command**: `cd frontend && npm run build`
- **Existing test count**: `<auto>`

## Risk Assessment
<!-- Identify potential blockers or unknowns before starting -->

- [ ] External dependencies (APIs, services) — availability confirmed?
- [x] Breaking changes to existing code — impact assessed? (UI layout changes)
- [ ] Large file generation — disk space sufficient?
- [ ] Long-running tests — timeout configured?

## Deliverables
<!-- Concrete outputs: files, features, endpoints, docs -->

- Backend indicator series includes MA + Bollinger Bands for price overlay (if approved).
- Frontend multi-pane chart stack with synchronized tooltip.

## Done-When
<!-- Final acceptance criteria. The task is DONE when ALL of these pass. -->

- [ ] Main price pane shows candlestick + MA/BB overlays (if available).
- [ ] Volume, RSI, MACD, Fracdiff each render as their own pane.
- [ ] Crosshair and X-axis range are synchronized across all panes.
- [ ] Floating tooltip follows crosshair and displays OHLC + indicator values with transparency.

## Final Validation Command
<!-- Single command that validates the entire deliverable. Runs at close-out. -->

```bash
cd frontend && npm run typecheck
```

## Demo Flow (optional)
<!-- Step-by-step instructions to demonstrate the finished product. -->

1. Open a Technical Analysis output page with chart artifacts.
2. Verify multi-pane layout and overlays.
3. Hover to see the aggregated tooltip.
