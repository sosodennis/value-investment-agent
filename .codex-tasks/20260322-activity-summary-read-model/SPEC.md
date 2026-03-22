# Task Specification

> Scope anchor for the task. Update only when goals or constraints change, and log the reason in PROGRESS.md.

## Task Shape
<!-- single-compact | single-full | epic | batch -->

- **Shape**: `single-full`

## Goals
<!-- What are we building? Be specific and concrete. -->

- Replace per-agent activity feed with a stable **Activity Summary Read Model** (segment-based) that removes duplicate/ambiguous events.
- Enforce `run_id` as a **required, non-empty** boundary for segment creation (no fallback/compat).
- Update `/thread/{thread_id}/activity` to return summary segments (breaking change, 0 backward compatibility).
- Ensure UI shows Running only for the **current** segment; historical segments show terminal status.
- Maintain clean layer boundaries and repository-only storage concerns.

## Non-Goals
<!-- What are we explicitly NOT doing? Prevents scope creep. -->

- No LangGraph framework modifications or custom stream modes.
- No internal/debug raw-events endpoint (defer until auth/feature flags exist).
- No compatibility shims for the old activity endpoint.
- No heavy event replay or high-dimensional queries.

## Constraints
<!-- Tech stack, style guide, performance limits, compatibility requirements -->

- `run_id` is mandatory for segment generation; events without `run_id` are rejected/ignored.
- Terminal statuses: `done`, `error`, `attention`, `degraded`.
- `running` is the only non-terminal status; UI highlights Running only when `is_current`.
- `idle` is not emitted as a status event; empty activity = idle state.
- Use existing runtime projection service as the read-model owner.
- Zero backward compatibility.

## Environment
<!-- Auto-filled by agent at init time -->

- **Project root**: `/Users/denniswong/Desktop/Project/value-investment-agent`
- **Language/runtime**: Python 3.12 (backend) + TypeScript/React (frontend)
- **Package manager**: `uv` (backend), `npm` (frontend)
- **Test framework**: `pytest`, `ruff`, `vitest`
- **Build command**: `cd frontend && npm run build`
- **Existing test count**: not sampled

## Risk Assessment
<!-- Identify potential blockers or unknowns before starting -->

- [x] Breaking changes to existing code — impact assessed (endpoint change + UI update in same slice)
- [ ] External dependencies (APIs, services) — availability confirmed?
- [ ] Large file generation — disk space sufficient?
- [ ] Long-running tests — timeout configured?

## Deliverables
<!-- Concrete outputs: files, features, endpoints, docs -->

- New Activity Summary segment model + projector + repository queries.
- Updated `/thread/{thread_id}/activity` endpoint returning summary segments.
- Updated frontend hook + UI to consume summary segments.
- Updated tests for backend projector/API + frontend hook/UI parsing.

## Done-When
<!-- Final acceptance criteria. The task is DONE when ALL of these pass. -->

- [ ] `/thread/{thread_id}/activity` returns summary segments (no raw events), honoring `limit` and cursor.
- [ ] UI shows deduped segments; Running only for current segment.
- [ ] Backend tests + lint pass; frontend tests pass.

## Final Validation Command
<!-- Single command that validates the entire deliverable. Runs at close-out. -->

```bash
uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_workspace_runtime_projection.py finance-agent-core/tests/test_thread_state_api.py -q \
  && uv run --project finance-agent-core python -m ruff check finance-agent-core/api/server.py finance-agent-core/src/runtime/workspace_runtime_projection finance-agent-core/tests/test_workspace_runtime_projection.py finance-agent-core/tests/test_thread_state_api.py \
  && cd frontend && npm test -- --run src/hooks/useAgentActivity.test.tsx
```

## Demo Flow (optional)
<!-- Step-by-step instructions to demonstrate the finished product. -->

1. Start a run and open the Workspace tab.
2. Confirm activity list shows unique segments with terminal statuses.
3. Confirm Running is only shown for the current active segment.
4. Click “View full history” to load more segments.
