# Child Progress Log

## Goal

Deliver a durable snapshot API for workspace restore.

## Current State

- Status: DONE (contracts synced)

## Next Action

- Proceed to Phase 4 SSE cursor work.

## Validation Notes

- `uv run --project finance-agent-core python -m ruff check finance-agent-core/api/server.py finance-agent-core/tests/test_thread_state_api.py`: pass.
- Focused pytest: `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_thread_state_api.py -q`: pass.
- Repo-wide pytest baseline remains red; not re-run in this slice.
- Contract generation: `bash scripts/generate-contracts.sh` completed.

## Implementation Summary

- `/thread/{thread_id}` now derives activity timeline, status history, active agent, and cursor from durable projection (no replay-buffer parsing).
- Snapshot DTO expanded with `activity_timeline`, `active_agent_id`, and `cursor` while keeping existing fields for compatibility.
- `WorkspaceRuntimeProjectionService` now exposes read helpers for recent activity and cursor retrieval.
- OpenAPI + frontend API contract regenerated for the new snapshot surface.
