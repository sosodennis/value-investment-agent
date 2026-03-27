# Task Specification

> Scope anchor for the task. Update only when goals or constraints change, and log the reason in PROGRESS.md.

## Task Shape
<!-- single-compact | single-full | epic | batch -->

- **Shape**: `single-full`

## Goals
<!-- What are we building? Be specific and concrete. -->

- Split `TechnicalAnalysisOutput` into smaller subcomponents to reduce monolith size while preserving behavior.
- Split `FundamentalAnalysisOutput` into smaller subcomponents to reduce monolith size while preserving behavior.
- Keep public exports and call sites stable.

## Non-Goals
<!-- What are we explicitly NOT doing? Prevents scope creep. -->

- No feature changes, visual redesign, or data wiring.
- No new dependencies or architectural rewrites.
- No accessibility or i18n work (out of scope per user).

## Constraints
<!-- Tech stack, style guide, performance limits, compatibility requirements -->

- Keep TypeScript types explicit and avoid `any`.
- Prefer local component extraction with minimal prop surfaces.
- Avoid touching unrelated files.

## Environment
<!-- Auto-filled by agent at init time -->

- **Project root**: `/Users/denniswong/Desktop/Project/value-investment-agent`
- **Language/runtime**: TypeScript / React / Next.js
- **Package manager**: npm (package-lock present)
- **Test framework**: vitest (vitest.config.mts)
- **Build command**: `npm run build` (not planned)
- **Existing test count**: (not checked)

## Risk Assessment
<!-- Identify potential blockers or unknowns before starting -->

- [ ] Breaking changes to component props — mitigated by keeping export contracts.
- [ ] Large refactor causing regressions — mitigate with typecheck.

## Deliverables
<!-- Concrete outputs: files, features, endpoints, docs -->

- New extracted subcomponent files for technical and fundamental outputs.
- Updated `TechnicalAnalysisOutput.tsx` and `FundamentalAnalysisOutput.tsx` to use subcomponents.

## Done-When
<!-- Final acceptance criteria. The task is DONE when ALL of these pass. -->

- [ ] `TechnicalAnalysisOutput` delegates to extracted subcomponents.
- [ ] `FundamentalAnalysisOutput` delegates to extracted subcomponents.
- [ ] Typecheck passes.

## Final Validation Command
<!-- Single command that validates the entire deliverable. Runs at close-out. -->

```bash
npm run typecheck
```

## Demo Flow (optional)
<!-- Step-by-step instructions to demonstrate the finished product. -->

1. Load workspace view and open technical/fundamental outputs.
2. Verify UI renders as before.
