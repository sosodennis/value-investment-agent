# Task Specification

> Scope anchor for the task. Update only when goals or constraints change, and log the reason in PROGRESS.md.

## Task Shape
<!-- single-compact | single-full | epic | batch -->

- **Shape**: `single-full`

## Goals

- Upgrade the Summary layout into enterprise-grade micro indicator cards.
- Keep Summary mode compact but informative (value + status + micro trend).

## Non-Goals

- No backend data changes or new indicators.
- No new charting libraries.
- No changes to layout mode logic outside Summary visuals.

## Constraints

- Reuse existing indicator series data.
- Maintain crosshair behavior unchanged.
- Keep UI consistent with current design language.

## Environment

- **Project root**: `/Users/denniswong/Desktop/Project/value-investment-agent`
- **Language/runtime**: TypeScript / React
- **Package manager**: npm
- **Test framework**: tsc (typecheck)
- **Build command**: `npm run typecheck` (from `frontend/`)
- **Existing test count**: N/A (typecheck only)

## Risk Assessment

- [ ] External dependencies (APIs, services) — availability confirmed?
- [x] Breaking changes to existing code — impact assessed?
- [ ] Large file generation — disk space sufficient?
- [ ] Long-running tests — timeout configured?

## Deliverables

- Enhanced Summary micro cards for RSI/MACD/FD.
- Sparkline rendering with lightweight SVG.

## Done-When

- [ ] Summary cards show value, status, and micro trend.
- [ ] Summary mode remains compact and readable.
- [ ] `npm run typecheck` passes.

## Final Validation Command

```bash
cd frontend && npm run typecheck
```

## Demo Flow (optional)

1. Switch indicator layout to Summary.
2. Validate RSI/MACD/FD cards show value + status + micro trend.
3. Confirm no layout regressions.
