# Child Task Specification

## Goal

Redesign durable thread snapshot and activity APIs so workspace restore is fully backed by checkpoints, durable projection, and persisted history.

## Scope

- `/thread/{thread_id}` redesign
- activity-oriented read API additions if needed
- DTO and parser contract updates

## Non-Goals

- SSE transport redesign
- frontend hook rewrite

## Done-When

- Durable snapshot APIs provide all workspace restore fields without reading replay buffers.
- Backend and contract tests cover active-run and completed-run restore.
