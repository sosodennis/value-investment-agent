# Child Task Specification

## Goal

Redesign the workspace SSE transport around stable event IDs and cursor-based reconnect.

## Scope

- event envelope / named event shape
- `id` / cursor semantics
- reconnect behavior and keepalive strategy

## Non-Goals

- Durable snapshot redesign
- Frontend restore ownership beyond contract adoption

## Done-When

- Stream reconnect resumes from cursor rather than whole-buffer replay.
- Focused tests cover duplicate suppression, reconnect, and keepalive behavior.
