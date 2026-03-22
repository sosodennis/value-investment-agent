# Child Task Specification

## Goal

Rewrite frontend restore so the Analysis Workspace hydrates from durable snapshot first and cursorized SSE second.

## Scope

- `useAgent` restore flow
- reducer hydration model
- page-level active-agent selection
- workspace process/history rendering alignment

## Non-Goals

- Backend schema changes
- Replay-buffer compatibility behavior

## Done-When

- Refresh during an active run restores the correct active agent and workflow panel.
- Completed-thread restore uses durable backend truth.
- No dual restore path remains in the frontend.
