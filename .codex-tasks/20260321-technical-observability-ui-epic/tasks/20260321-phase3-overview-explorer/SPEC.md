# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- Build the `Overview` and `Event Explorer` views for the new Technical Observability page.
- Surface backlog, headline metrics, and event-level drill-down using the new UI APIs.
- Keep the page readable by separating summary and investigation concerns.

## Non-Goals

- Build cohort analysis or calibration-readiness views.
- Add public exports or external dashboard integrations.
- Rework the backend truth model.

## Constraints

- Views must read from the shared filter workspace.
- Event drill-down must preserve links back to relevant artifacts or report references.
- Loading, empty, and degraded states must be explicit.

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

- Overview cards and backlog-focused summary view
- Event explorer table or list
- Event detail drill-down drawer or panel
- Focused UI tests

## Done-When

- [ ] Overview shows meaningful observability metrics
- [ ] Event explorer supports internal investigation workflows
- [ ] Loading, empty, and degraded states are explicit
- [ ] Frontend tests, typecheck, and lint pass

## Final Validation Command

```bash
cd frontend && npm run test && npm run typecheck && npm run lint
```
