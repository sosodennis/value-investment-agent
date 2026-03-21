# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- Build the `Cohort Analysis` and `Calibration Readiness` views for the Technical Observability page.
- Let internal users inspect grouped behavior across timeframe horizon and logic-version slices.
- Surface calibration sample sufficiency and drop reasons without implementing automated recalibration.

## Non-Goals

- Add a recalibration job or fitting workflow.
- Build a public-facing dashboard.
- Collapse raw and approved label semantics into one UI lens.

## Constraints

- Grouping views must stay aligned to the ADR dimensions.
- The UI must keep `raw outcomes` and `approved label snapshots` as distinct lenses.
- Calibration readiness should stay a monitoring surface, not a control panel for fitting.

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

- Cohort grouping view
- Calibration-readiness summary view
- Lens controls for raw vs approved semantics
- Focused UI tests

## Done-When

- [ ] Cohort analysis is readable and filter-driven
- [ ] Calibration readiness is visible with sample sufficiency or drop reasons
- [ ] Raw and approved label lenses are clearly separated
- [ ] Frontend tests, typecheck, and lint pass

## Final Validation Command

```bash
cd frontend && npm run test && npm run typecheck && npm run lint
```
