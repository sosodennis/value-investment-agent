# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- Add the dedicated `/technical-observability` route and a minimal navigation entry.
- Build a shared filter workspace and typed fetch hook for the page.
- Keep the existing analysis workspace at `/` focused on live execution.

## Non-Goals

- Build all data views.
- Merge observability into `TechnicalAnalysisOutput`.
- Redesign the global app shell beyond what the new route requires.

## Constraints

- The new page must be a dedicated route.
- The fetch layer must use typed contracts rather than ad-hoc JSON access.
- Shared filter state should live in a single page workspace, not in independent tab-local silos.

## Environment

- **Project root**: `/Users/denniswong/Desktop/Project/value-investment-agent`
- **Language/runtime**: TypeScript / React 19 / Next.js 16
- **Package manager**: `npm`
- **Test framework**: `vitest`
- **Build command**: `cd frontend && npm run build`
- **Existing test count**: Not captured in task scaffold

## Risk Assessment

- [ ] External dependencies (APIs, services) — availability confirmed?
- [x] Breaking changes to existing code — impact assessed?
- [x] Large file generation — disk space sufficient?
- [ ] Long-running tests — timeout configured?

## Deliverables

- New route page
- Shared filter bar and route workspace shell
- Typed observability fetch hook
- Navigation entry from the current UI

## Done-When

- [ ] `/technical-observability` exists
- [ ] Shared filter state is centralized
- [ ] Main workspace remains cleanly separated
- [ ] Frontend tests, typecheck, and lint pass

## Final Validation Command

```bash
cd frontend && npm run test && npm run typecheck && npm run lint
```
