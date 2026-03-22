# Epic Specification

## Goal

- Implement the enterprise-grade runtime durability upgrade described in `/Users/denniswong/Desktop/Project/value-investment-agent/docs/analysis-workspace-runtime-durability-adr-2026-03-21.md` so the Analysis Workspace restores reliably after refresh, reconnect, and process churn without relying on in-memory replay buffers.

## Non-Goals

- Keep the current replay-buffer restore path as fallback.
- Introduce WebSockets as a transport replacement.
- Partially harden refresh while leaving completed-history durability unresolved.
- Add product-facing workflow dashboards beyond the existing analysis workspace.

## Constraints

- Prefer one clean migration over compatibility layers.
- Treat LangGraph thread/checkpoint state plus durable runtime projection as the only restore truth.
- Keep SSE as delta transport only, with cursor-based resume semantics.
- Persist agent identity as first-class durable message truth.
- Keep the new snapshot/stream contract as close as practical to LangChain/LangGraph thread/run/rejoin-stream patterns.
- Remove replay-buffer-based restore logic in the same program.
- Preserve strict typing and existing repository architecture boundaries.

## Risk Assessment

- Runtime event projection can drift from graph semantics if ownership is unclear.
- Cursor mistakes can create duplicate or skipped SSE updates.
- Snapshot API redesign can regress interrupt handling and agent selection if not covered end-to-end.
- Projection/checkpoint divergence needs an explicit eventual-consistency and reconciliation stance.
- Deployment gaps around HTTP/2 or retention/TTL can undermine runtime durability even if the code path is correct.
- Legacy removal is necessary but increases rollback sensitivity near cutover.

## Child Deliverables

- Phase 1 durable runtime projection schema and repository
- Phase 2 runtime event writer and projection ownership refactor
- Phase 3 durable thread snapshot and activity API redesign
- Phase 4 cursor-based SSE transport redesign
- Phase 5 frontend snapshot-first restore rewrite
- Phase 6 legacy replay-path removal and end-to-end hardening

## Dependency Notes

- Child 2 depends on child 1 because runtime writes need the new durable projection schema and repository.
- Child 3 depends on child 2 because the new thread snapshot API should read from real projection data.
- Child 4 depends on child 3 because cursor semantics and transport payloads should align with the new snapshot contract.
- Child 5 depends on child 4 because the frontend should adopt the final snapshot/cursor contract only once it stabilizes.
- Child 6 depends on children 3, 4, and 5 because legacy removal should only happen after the new restore path is end-to-end green.

## Child Task Types

- `single-full`

## Done-When

- [ ] Every row in `SUBTASKS.csv` is `DONE`
- [ ] The implementation satisfies the ADR success criteria
- [ ] Replay-buffer-based workspace restore has been deleted
- [ ] Validation gates for each phase have explicit passing evidence
