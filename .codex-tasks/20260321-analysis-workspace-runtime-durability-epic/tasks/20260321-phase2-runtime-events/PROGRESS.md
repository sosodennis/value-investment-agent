# Child Progress Log

## Goal

Move workspace runtime truth from transient replay memory into durable event projection writes.

## Current State

- Status: DONE (focused validation complete)

## Next Action

- Proceed to Phase 3 thread snapshot API once ready.

## Validation Notes

- `uv run --project finance-agent-core python -m ruff check finance-agent-core/api/server.py finance-agent-core/src/runtime/workspace_runtime_projection`: pass.
- Focused pytest: `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_workspace_runtime_projection.py finance-agent-core/tests/test_workspace_runtime_projection_runtime_service.py -q`: pass.
- Repo-wide pytest baseline remains red; not re-run in this slice.

## Implementation Summary

- Added runtime projection service to map AgentEvent -> projection writes with cursor updates and idempotent duplicate handling.
- Stream event generator now persists activity/interrupt/lifecycle/error events without blocking SSE delivery.
- Sequence initialization for new runs and resumes now uses durable cursor to avoid seq_id reuse across restarts.
