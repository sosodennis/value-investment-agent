# Task Specification

> Scope anchor for the task. Update only when goals or constraints change, and log the reason in PROGRESS.md.

## Task Shape
<!-- single-compact | single-full | epic | batch -->

- **Shape**: `single-full`

## Goals
<!-- What are we building? Be specific and concrete. -->

- Replace `transition-all` / `transition: all` with explicit transition properties in frontend UI code.
- Update targeted UI copy to use ellipsis `…` and Title Case for the landing analyze button.

## Non-Goals
<!-- What are we explicitly NOT doing? Prevents scope creep. -->

- Accessibility remediation beyond the requested copy/transition updates.
- i18n changes (site remains en-US only).
- Refactors or data wiring for demo content.

## Constraints
<!-- Tech stack, style guide, performance limits, compatibility requirements -->

- Keep changes minimal and localized to copy + transition utilities.
- Preserve existing visual design intent and Tailwind usage.
- Do not introduce new dependencies.

## Environment
<!-- Auto-filled by agent at init time -->

- **Project root**: `/Users/denniswong/Desktop/Project/value-investment-agent`
- **Language/runtime**: TypeScript / React / Next.js
- **Package manager**: npm (package-lock present)
- **Test framework**: vitest (vitest.config.mts)
- **Build command**: (not run)
- **Existing test count**: (not checked)

## Risk Assessment
<!-- Identify potential blockers or unknowns before starting -->

- [ ] External dependencies (APIs, services) — availability confirmed?
- [ ] Breaking changes to existing code — impact assessed?
- [ ] Large file generation — disk space sufficient?
- [ ] Long-running tests — timeout configured?

## Deliverables
<!-- Concrete outputs: files, features, endpoints, docs -->

- Updated frontend source files with explicit transitions.
- Updated UI copy strings using ellipsis and Title Case where specified.

## Done-When
<!-- Final acceptance criteria. The task is DONE when ALL of these pass. -->

- [ ] `transition-all` and `transition: all` are removed from `frontend/src`.
- [ ] Target copy strings are updated (ellipsis + Title Case for Analyze button).
- [ ] Final validation command passes.

## Final Validation Command
<!-- Single command that validates the entire deliverable. Runs at close-out. -->

```bash
! rg "transition-all" frontend/src \
  && ! rg "transition: all" frontend/src \
  && ! rg "ANALYZE" frontend/src \
  && ! rg "\"[^\"]*\\.\\.\\.[^\"]*\"|'[^']*\\.\\.\\.[^']*'" frontend/src
```

## Demo Flow (optional)
<!-- Step-by-step instructions to demonstrate the finished product. -->

1. Open landing page and confirm Analyze button label + placeholder copy.
2. Navigate to agent outputs to confirm updated ellipsis copy.
