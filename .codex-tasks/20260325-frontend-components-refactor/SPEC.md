# Task Specification

> Scope anchor for the task. Update only when goals or constraints change, and log the reason in PROGRESS.md.

## Task Shape
<!-- single-compact | single-full | epic | batch -->

- **Shape**: `single-full`

## Goals
<!-- What are we building? Be specific and concrete. -->

- Reorganize `frontend/src/components` per approved plan (Phase 1 + Phase 2 + charts into technical-analysis).
- Normalize `agent-outputs` feature subfolders and shared kernel.
- Colocate workspace-only components under `components/workspace`.
- Update imports/tests to match new structure and remove stale paths.

## Non-Goals
<!-- What are we explicitly NOT doing? Prevents scope creep. -->

- No UI redesign or behavioral changes beyond import paths.
- No a11y improvements (out of scope for demo).
- No localization changes (en-US only).
- No backend changes.

## Constraints
<!-- Tech stack, style guide, performance limits, compatibility requirements -->

- Demo-focused; keep changes minimal and reversible.
- Preserve robustness fallbacks and compatibility behavior.
- Avoid barrel exports for bundle hygiene.

## Environment
<!-- Auto-filled by agent at init time -->

- **Project root**: `/Users/denniswong/Desktop/Project/value-investment-agent`
- **Language/runtime**: TypeScript / Node / Next.js 16
- **Package manager**: npm
- **Test framework**: vitest
- **Build command**: `npm run build`
- **Existing test count**: not checked

## Risk Assessment
<!-- Identify potential blockers or unknowns before starting -->

- [x] Breaking changes to existing code — import paths must be updated atomically.
- [ ] External dependencies (APIs, services) — availability confirmed?
- [ ] Large file generation — disk space sufficient?
- [ ] Long-running tests — timeout configured?

## Deliverables
<!-- Concrete outputs: files, features, endpoints, docs -->

- New component folder structure with updated imports.
- Updated tests/mocks referencing moved components.
- Removal of unused barrel file if no longer referenced.

## Done-When
<!-- Final acceptance criteria. The task is DONE when ALL of these pass. -->

- [ ] All planned moves complete and old paths removed.
- [ ] `rg` sweep shows no imports from deprecated paths.
- [ ] Lint/typecheck/tests run or explicitly deferred with reason.

## Final Validation Command
<!-- Single command that validates the entire deliverable. Runs at close-out. -->

```bash
npm run lint && npm run typecheck && npm run test
```

## Demo Flow (optional)
<!-- Step-by-step instructions to demonstrate the finished product. -->

1. Navigate to workspace page and open agent output tabs.
2. Verify technical analysis charts render as before.
3. Open landing page to ensure roster and detail panels render.
