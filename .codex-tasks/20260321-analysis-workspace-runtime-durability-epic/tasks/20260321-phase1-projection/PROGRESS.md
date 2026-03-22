# Child Progress Log

## Goal

Create the durable runtime projection foundation for Analysis Workspace restore.

## Current State

- Status: DONE (validation run; repo-wide pytest baseline remains red)
- Durable runtime projection schema, repository port/adapter, and focused tests are implemented.

## Next Action

- Proceed to Phase 2 runtime events once the epic moves forward.

## Validation Notes

- `uv run --project finance-agent-core python -m ruff check finance-agent-core`: pass (after fixing pre-existing script import ordering).
- `uv run --project finance-agent-core python -m pytest finance-agent-core/tests -q`: fails with baseline issues (67 failed, 5 skipped).
- Focused validation: `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_workspace_runtime_projection.py -q` passed.

## Implementation Summary

- Added `workspace_runtime_activity_events` and `workspace_runtime_cursors` ORM tables plus `chat_history.agent_id` with indexes.
- Introduced `src/runtime/workspace_runtime_projection` with domain contracts, derivation helpers, repository port, and SQLAlchemy adapter.
- Updated history persistence to capture `agent_id` from message metadata.
- Removed empty interface package to avoid empty-layer violations.
