# Analysis Workspace Runtime Durability ADR

Date: 2026-03-21
Status: Accepted
Owner: Workflow Runtime + Frontend Workspace

## Decision Summary

We have replaced the Analysis Workspace refresh/reconnect model with a durable runtime architecture built on two explicit planes:

- a durable state plane backed by LangGraph threads, checkpoints, and a DB-backed workflow activity projection
- a live event plane backed by cursor-based SSE for incremental updates only

We do not preserve the former `in-memory replay buffer + ad-hoc /thread snapshot + reducer dedupe` restore path.

The upgraded implementation now:

- make `thread/checkpoint/history + durable runtime projection` the only truth source for workspace restoration
- treat SSE as a transport for deltas, not as the source of truth
- support cursor-based reconnect using event IDs / sequence IDs
- persist agent identity as first-class durable message truth for per-agent history and interrupt restore
- restore active agent, current task, interrupts, and recent workflow activity after refresh without depending on process memory
- removed legacy replay-buffer restore logic in the same migration

The upgraded implementation does not:

- keep dual restore paths for compatibility
- rely on `event_replay_buffers` for refresh or post-completion history
- keep `localStorage` or stale `node_statuses` as authoritative workflow state

## Context

The current runtime UX is centered on:

- [page.tsx](/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/app/page.tsx)
- [useAgent.ts](/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/hooks/useAgent.ts)
- [useAgentReducer.ts](/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/hooks/useAgentReducer.ts)
- [server.py](/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/api/server.py)

Previously, refresh restoration depended on:

- `GET /thread/{thread_id}` for a partial snapshot
- `GET /stream/{thread_id}` replaying `event_replay_buffers`
- reducer-side `seq_id` dedupe
- transient runtime state held in process memory

That legacy shape was not durable enough for an enterprise-grade operator workspace:

- active workflow display can be wrong after refresh if snapshot state lags stream state
- completed workflow history could not be restored once the in-memory replay buffer was cleaned up
- SSE reconnect behavior did not follow the standard cursor-based model
- the frontend had to guess truth by merging stale snapshot fields with replayed events

This also diverges from the architecture encouraged by official LangGraph and SSE documentation:

- LangGraph persistence centers durable execution on threads, checkpoints, and state history
- LangGraph streaming provides explicit `updates`, `values`, `tasks`, and `checkpoints` stream modes
- LangGraph durable execution assumes deterministic and idempotent workflows
- MDN documents SSE reconnect around `id`, `retry`, named `event` messages, and keepalive comments

## External Verification

The decision is based on the following official sources:

- LangGraph persistence: [https://docs.langchain.com/oss/python/langgraph/persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- LangGraph streaming: [https://docs.langchain.com/oss/python/langgraph/streaming](https://docs.langchain.com/oss/python/langgraph/streaming)
- LangGraph subgraphs: [https://docs.langchain.com/oss/python/langgraph/use-subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)
- LangGraph durable execution: [https://docs.langchain.com/oss/javascript/langgraph/durable-execution](https://docs.langchain.com/oss/javascript/langgraph/durable-execution)
- MDN SSE: [https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events)
- MDN EventSource: [https://developer.mozilla.org/en-US/docs/Web/API/EventSource](https://developer.mozilla.org/en-US/docs/Web/API/EventSource)

The design conclusions we are adopting from those sources are:

- workflow restoration should come from durable thread/checkpoint state, not an in-memory event cache
- `updates`, `tasks`, and `checkpoints` are better aligned with UI/runtime state than a debug-style catch-all stream
- subgraph activity should be surfaced deliberately through parent-visible state or projection ownership
- durable execution quality depends on deterministic/idempotent runtime behavior
- SSE reconnect should use event IDs / cursors and server-declared retry behavior instead of whole-buffer replay
- the browser `EventSource` API only exposes URL plus credentials mode, so initial cursor handoff should use the URL while reconnect can rely on SSE event IDs / `Last-Event-ID`
- LangChain frontend guidance already centers on persisted threads plus reconnect/join semantics, so our custom contract should converge toward that model instead of diverge further
- mature read-model/event-sourcing systems treat projections as eventually consistent and rebuildable from durable history
- production SSE-heavy workflows should assume HTTP/2 and explicit retention/TTL policy rather than leaving those as implicit infra details

## Decision

### 1. Durable runtime projection becomes a first-class backend capability

We have added a DB-backed append-only runtime projection for Analysis Workspace workflow activity.

Its scope is:

- thread lifecycle state for the workspace
- per-agent / per-node activity transitions
- interrupt visibility needed by the workspace
- recent activity timeline for the selected thread

This projection is a UI/governance read model. It does not replace LangGraph checkpoints. It complements them by serving the frontend a stable workspace-oriented runtime view.

### 2. `/thread/{thread_id}` becomes a durable workspace snapshot API

`/thread/{thread_id}` is now the single authoritative restore contract for the workspace.

It is rebuilt from:

- LangGraph checkpointed state
- durable runtime projection
- durable chat history with persisted agent identity

It does not read:

- in-memory replay buffers
- ad-hoc transient queues

### 3. SSE becomes delta-only and cursor-based

`/stream/{thread_id}` is redesigned so that:

- each event carries a stable event ID / sequence ID
- reconnect resumes from `Last-Event-ID` or explicit `after_seq`
- the stream emits named events and keepalive comments
- the stream no longer needs whole-buffer replay to restore UI state

The intended behavior is:

- first attach from the snapshot cursor via URL/query parameter
- later reconnect from SSE event IDs

### 4. Frontend restore becomes snapshot-first, delta-second

The frontend restore contract is now:

1. fetch durable workspace snapshot
2. hydrate local UI state from that snapshot
3. connect SSE from the returned cursor
4. merge deltas only after the cursor boundary

`localStorage` is retained only for lightweight UI preferences such as the last selected agent/tab, not for workflow truth.

### 5. Projection consistency is eventual, with checkpoints authoritative

The durable runtime projection is a derived read model.

The consistency stance is:

- LangGraph checkpointed thread state is the authoritative runtime source
- runtime projection is eventually consistent
- projection rows must be append-only and replayable
- the system must support reconciliation / rebuild of projection state from durable thread history when needed

### 6. Deployment assumptions are explicit

The production target assumes:

- HTTP/2-capable delivery for SSE-heavy operator workflows
- explicit retention / TTL policy for thread/checkpoint data
- explicit retention policy for runtime projection tables

### 7. Compatibility code is explicitly rejected

We do not preserve:

- old replay-buffer restore behavior as a fallback
- dual parsing paths for legacy and new thread restore formats
- temporary merge logic that guesses between stale `node_statuses` and transient stream state

This is a one-time migration to a cleaner architecture.

## Architectural Shape

### Durable state plane

Truth sources:

- LangGraph thread/checkpoint state
- chat history table
- new runtime activity projection table(s)

Responsibilities:

- current active agent
- current active task
- workflow status timeline
- interrupt state
- latest durable cursor / sequence
- durable per-agent message ownership

### Live event plane

Transport:

- SSE only

Responsibilities:

- deliver post-snapshot deltas
- support initial attach from snapshot cursor via URL parameter
- support reconnect from cursor via SSE event IDs
- expose named event types for the frontend reducer

Non-responsibilities:

- reconstructing history
- restoring workflow state from scratch

## Detailed Implementation Shape

### Backend ownership

- `domain`
  - deterministic runtime projection semantics
  - active agent derivation policy
  - cursor semantics
- `application`
  - ports and orchestration for projection writes and snapshot reads
- `interface`
  - workspace snapshot DTOs
  - SSE event DTOs / serializers
- `infrastructure`
  - SQLAlchemy projection repository
  - stream cursor storage/lookup
  - FastAPI transport adapter

### Frontend ownership

- route shell remains in [page.tsx](/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/app/page.tsx)
- runtime session hook remains in [useAgent.ts](/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/hooks/useAgent.ts)
- reducer remains in [useAgentReducer.ts](/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/hooks/useAgentReducer.ts)

But the responsibilities change:

- snapshot hydration becomes explicit and durable
- selected agent derives from durable active state first
- delta processing begins strictly after the durable cursor

## Consequences

### Positive

- refresh behavior becomes predictable and durable
- completed workflow history can survive process restart and replay-buffer cleanup
- SSE becomes standards-aligned and easier to reason about
- frontend logic becomes simpler because it no longer guesses truth from multiple weak sources
- future governance, operator tooling, and auditability improve
- projection repair is possible because checkpointed thread state remains authoritative

### Negative

- this is a large migration across runtime, transport, persistence, API, and frontend restore
- implementation will require new schema, new API contracts, and end-to-end tests
- the old quick-and-dirty restore path must be deleted in the same program
- projection consistency and reconciliation rules must be explicitly designed
- deployment/infrastructure settings now become part of the runtime durability contract

### Neutral but important

- checkpoints remain the canonical workflow engine durability mechanism
- the new runtime projection is intentionally a UI/runtime read model, not a replacement for LangGraph state

## Rejected Alternatives

### 1. Keep patching the replay buffer path

Rejected because:

- it remains process-memory dependent
- it cannot solve completed-history durability cleanly
- it keeps frontend restore logic coupled to ad-hoc backend behavior

### 2. Keep dual restore paths during migration

Rejected because:

- it creates long-lived compatibility code
- it would increase reducer and API complexity
- it directly conflicts with the goal of minimizing future technical debt

### 3. Replace SSE with WebSockets first

Rejected because:

- SSE is sufficient for server-to-client workflow deltas
- the main issue is durability and resume semantics, not bidirectional transport
- standard EventSource reconnect behavior already fits the use case

## Rollout Strategy

The migration should proceed in six phases:

1. Durable runtime projection schema and repository
2. Runtime event write path refactor
3. Durable thread snapshot and activity API redesign
4. Cursor-based SSE redesign
5. Frontend snapshot-first restore rewrite
6. Legacy replay-path removal and hardening

No legacy compatibility shim should survive beyond the phase that migrates its callers.

## Done-When

- workspace refresh restores active process state from durable backend truth
- completed threads retain recent workflow activity without depending on process memory
- SSE reconnect resumes from cursor rather than whole-buffer replay
- the frontend no longer guesses truth from stale `node_statuses`
- replay-buffer-based restore logic is removed
