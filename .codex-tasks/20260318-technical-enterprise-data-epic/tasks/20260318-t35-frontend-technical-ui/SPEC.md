# T35 Spec — Frontend Technical UI Evidence / Quality / Policy Alerts

## Goal
Render the new enterprise-grade technical report fields in the primary frontend experience so users can see:
- key deterministic evidence
- quality / coverage state
- policy-alert summary

without having to expand raw artifact sections first.

## Scope
- `frontend/src/components/agent-outputs/TechnicalAnalysisOutput.tsx`
- `frontend/src/components/agent-outputs/technical-wording.ts`
- frontend tests for wording and render behavior

## Non-Goals
- No backend contract changes
- No new compatibility shim
- No redesign of the chart stack or artifact expansion panels

## Acceptance Criteria
- Main technical UI renders top-level `Key Evidence`, `Quality & Coverage`, and `Policy Alerts` readouts from report-level fields.
- UI uses wording facade helpers for new quality / lifecycle microcopy instead of scattering new copy decisions in the component.
- Existing expandable artifact panels remain available for deeper inspection.
- Frontend tests cover at least:
  - new wording helpers
  - render of report-level quality/evidence/alert sections

## Validation
- `npm --prefix frontend run test -- src/components/agent-outputs/technical-wording.test.ts src/components/agent-outputs/TechnicalAnalysisOutput.test.tsx src/types/agents/artifact-parsers.test.ts`
- `npm --prefix frontend run typecheck`
