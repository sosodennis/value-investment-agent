# Epic Progress Log

## Goal

Ship the enterprise-grade runtime durability upgrade for the Analysis Workspace without compatibility restore paths.

## Current State

- Status: Planning complete, execution not started.
- Active child: Phase 1 durable runtime projection schema and repository.
- Truth source: `SUBTASKS.csv`.

## Decisions Locked

- Replay-buffer-based restore is not a fallback and not part of the target state.
- Durable restore truth = LangGraph checkpoints + durable runtime projection + durable chat history.
- SSE is delta transport only and must support cursor-based resume.
- Frontend restore will be snapshot-first, delta-second.

## External Verification Summary

- LangGraph persistence and state history support a durable thread/checkpoint model.
- LangGraph streaming recommends explicit stream modes such as `updates`, `tasks`, and `checkpoints`.
- LangGraph durable execution emphasizes deterministic and idempotent runtime behavior.
- MDN SSE defines `id`, `retry`, named `event`s, keepalive comments, and automatic reconnect semantics.

## Risks To Watch

- Projection semantics drifting from graph truth.
- Cursor gaps or duplicate deliveries during reconnect.
- Frontend reducer regressions during cutover from replay-based hydration.
- Interrupt handling regressions when `/thread` snapshot semantics change.

## Next Action

- Start child #1 and define the durable runtime projection schema, repository contract, and tests before touching stream transport or frontend restore.
