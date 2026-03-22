# Task Specification

> Scope anchor for the task. Update only when goals or constraints change, and log the reason in PROGRESS.md.

## Task Shape

- **Shape**: single-full

## Goals

- Consolidate agent artifact parser typing by replacing scattered `Record<string, unknown>` with a unified JSON object type and shared decoder helpers.
- Reduce duplication of `toRecord`/`toRecordArray` guards across agent parser modules.
- Keep artifact parsing behavior stable while improving type clarity.

## Non-Goals

- No changes to backend artifact contracts or API responses.
- No edits to technical observability UI or monitoring pages.
- No compatibility shims or parallel legacy types.

## Constraints

- Frontend-only refactor (`frontend/src/types/agents/*` and shared type helpers).
- Preserve existing runtime parsing behavior and error messages where feasible.
- Keep changes minimal and test-backed.

## Environment

- **Project root**: `/Users/denniswong/Desktop/Project/value-investment-agent`
- **Language/runtime**: TypeScript / React
- **Package manager**: npm
- **Test framework**: vitest
- **Build command**: `cd frontend && npm run build`
- **Existing test count**: 788 backend tests (frontend tests are separate)

## Risk Assessment

- [ ] External dependencies (APIs, services) — availability confirmed?
- [x] Breaking changes to existing code — impact assessed?
- [ ] Large file generation — disk space sufficient?
- [ ] Long-running tests — timeout configured?

## Deliverables

- Unified JSON record type helper for agent parsers.
- Updated agent parser modules and agent output types to use the shared helper/type.
- Updated tests or contract fixtures if required.

## Done-When

- [ ] `Record<string, unknown>` usage in `frontend/src/types/agents` is consolidated into shared JSON types/helpers.
- [ ] Frontend typecheck and tests pass.
- [ ] No behavioral regression in artifact parsing (smoke verification by type guards and existing tests).

## Final Validation Command

```bash
cd frontend && npm run typecheck && npm run test
```

## Demo Flow (optional)

1. Run the validation command above to ensure typing and parsing are intact.
