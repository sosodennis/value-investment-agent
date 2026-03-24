# Task Specification

> Scope anchor for the task. Update only when goals or constraints change, and log the reason in PROGRESS.md.

## Task Shape

- **Shape**: `single-full`

## Goals

- Verify whether `status_history` is actually produced/used in backend AgentState and subAgentState flow (including API responses).
- If `status_history` is unused end-to-end, remove it from backend → contracts → frontend types/parsers.
- If `status_history` is used, document evidence and leave it intact.

## Non-Goals

- Do not change agent execution logic or valuation behavior.
- Do not refactor unrelated runtime projection or observability storage.
- Do not remove `node_statuses`.

## Constraints

- Keep API behavior stable unless `status_history` is confirmed unused.
- Any removal must update contracts and frontend parsing in the same slice.
- No compatibility shims unless explicitly requested.

## Environment

- **Project root**: `/Users/denniswong/Desktop/Project/value-investment-agent`
- **Language/runtime**: Python (backend) + TypeScript/React (frontend)
- **Package manager**: `pip/uv` (backend), `npm` (frontend)
- **Test framework**: `pytest` (backend), `vitest` (frontend)
- **Build command**: `npm test -- --run` (frontend)
- **Existing test count**: 103 (frontend)

## Risk Assessment

- [ ] External dependencies (APIs, services) — availability confirmed?
- [x] Breaking changes to existing code — impact assessed?
- [ ] Large file generation — disk space sufficient?
- [ ] Long-running tests — timeout configured?

## Deliverables

- Evidence-backed determination on `status_history` usage.
- If unused: removal in backend models/API + contracts + frontend parsers/tests.

## Done-When

- [ ] Investigation confirms usage or non-usage with file/line evidence.
- [ ] If unused, removal is complete and validated across backend + frontend.
- [ ] If used, no removal performed and evidence recorded.

## Final Validation Command

```bash
cd /Users/denniswong/Desktop/Project/value-investment-agent/frontend && npm test -- --run
```

## Demo Flow (optional)

1. Call `/thread/{thread_id}` and verify `status_history` presence when activity exists.
