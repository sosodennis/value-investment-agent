# Deletion ledger

This ledger is authoritative for the hard cutover. `Delete` means remove the
symbol/path after all in-repository callers move in the same implementation
issue. `Rename` means update backend schema, generated OpenAPI, frontend parser,
fixtures, and tests together. `Retain` requires a current owner and a concrete
use listed in the ownership inventory.

## Public routes

| Current path or route | Action | Owner/issue | Reason |
| --- | --- | --- | --- |
| `/history/{thread_id}` | Rename to `/api/v1/threads/{thread_id}/messages` | Analysis runtime / #145 | Versioned plural resource; history is a message view |
| `/thread/{thread_id}` | Rename to `/api/v1/threads/{thread_id}` | Analysis runtime / #145 | Versioned thread resource |
| `/thread/{thread_id}/agents` | Delete | Analysis runtime / #145 | Duplicate scalar status view; snapshot/activity is canonical |
| `/thread/{thread_id}/activity` | Rename to `/api/v1/threads/{thread_id}/activities` | Analysis runtime / #145 | Activity is a first-class typed projection |
| `/stream/{thread_id}` | Rename to `/api/v1/threads/{thread_id}/events` | Analysis runtime / #145 | SSE is an event stream with cursor replay |
| `POST /stream` | Rename to `POST /api/v1/threads/{thread_id}/runs` | Analysis runtime / #145 | Run is the resource; thread identity must be explicit |
| Missing cancel route | Add `POST /api/v1/threads/{thread_id}/runs/{run_id}/cancel` | Analysis runtime / #145 | Cancellation must be an explicit typed command |
| `/api/artifacts/{artifact_id}` | Rename to `/api/v1/artifacts/{artifact_id}` | Artifact store / #145 | Public API versioning |
| `/api/auth/*` | Rename to `/api/v1/auth/*` | Auth / #145 | Public API versioning |
| `/api/llm/*` | Rename to `/api/v1/llm/*` | LLM settings / #145 | Public API versioning |
| `/api/search/*` | Rename to `/api/v1/search/*` | Search settings / #145 | Public API versioning |
| `/api/observability/*` | Rename to `/api/v1/observability/*` | Technical observability / #145 | Public API versioning |
| `/health`, `/ready` | Retain | Composition root/operations / #145 | Operational probes are not user resources |

## Events, state, and parsers

| Current item | Action | Owner/issue | Reason |
| --- | --- | --- | --- |
| `internal_progress` in root `AgentState` | Delete | #148 then #145 | Arbitrary flat node/status map is not a product contract |
| `internal_progress` in intent/news/debate/fundamental/technical state | Delete | #148 then #145 | Same field has multiple unowned writers |
| `node_statuses` | Delete from public snapshot/events | #148 then #145/#146 | Cannot represent nested or repeated activities |
| `current_node` and `active_agent_id` | Delete from public snapshot/events | #148 then #145/#146 | Scalar current-node inference is ambiguous for parallel work |
| `agent.status` | Delete as public activity signal | #148 then #145/#146 | Replace with normalized `workflow.activity`; raw adapter event is internal |
| `agent.lifecycle` | Delete as public activity signal | #148 then #145/#146 | Lifecycle belongs in typed run/activity projection |
| `state.update` | Delete from public SSE | #148 then #145/#146 | Raw LangGraph state must not cross the app boundary |
| `content.delta` | Retain as separate transient content event, or rename in #148 if chosen | #148 then #145/#146 | Content is not activity; replayability must be explicit |
| `interrupt.request` | Delete; persist typed request on a waiting `workflow.activity` | #147 | Replay, snapshot, and resume share one activity identity and cursor |
| `error` with raw exception message | Rename to stable error envelope | #145/#146 | No provider prompts, stack traces, or internal details at boundary |
| `src/interface/events/adapters.py` raw LangGraph mapping | Replace | #145 | Adapter becomes backend-owned normalizer to `workflow.activity` |
| `frontend/src/types/protocol.ts` union of legacy event names | Replace | #146 | One feature parser consumes the frozen envelope and fixtures |
| `contracts/fixtures/sse-events-v1.json` | Delete | #147 | The durable activity contract owns replayable workflow events |
| `frontend/src/hooks/useAgentStatus.ts` | Delete or absorb into workspace activity reducer | #146 | Duplicate status ownership |
| `frontend/src/hooks/useAgentActivity.ts` | Move into workspace feature | #146 | Feature owns activity API/parser |
| `frontend/src/hooks/useAgent.ts` | Move into workspace feature | #146 | Feature owns run/SSE lifecycle |
| `frontend/src/lib/agent-session-state.ts` | Move/replace with typed workspace state | #146 | Global session shape mixes runtime and view concerns |

## Persistence and database

| Current item | Action | Owner/issue | Reason |
| --- | --- | --- | --- |
| `workspace_runtime_activity_segments` table/model | Delete | #145 | Scalar segment cannot represent nested/repeated activity |
| `workspace_runtime_run_statuses` table/model | Replace | #145 | Run projection must use typed lifecycle and owner boundary |
| `workspace_runtime_cursors` table/model | Replace | #145 | Cursor advances atomically with normalized event append |
| `workspace_runtime_activity_events.agent_id/node/event_type/status` fields | Replace | #145 | Store the #148 envelope; no legacy scalar columns |
| `ChatMessage.metadata_` browser-shape aliases (`agentId`, `type`, `data`) | Rename/rebuild | #145/#146 | Database model must not expose frontend compatibility shape |
| `Artifact.thread_id` without owner check | Rebuild with owner relationship | #145 | Artifact lookup must authorize before read |
| Existing database rows/checkpoints | Delete by fresh setup | #145/#147 | Pre-release hard cutover has no migration requirement |

## Modules and imports

| Current item | Action | Owner/issue | Reason |
| --- | --- | --- | --- |
| Graph/run/replay/SSE policy in `finance-agent-core/api/server.py` | Move then delete private helpers | #145 | Composition root must remain thin |
| `src/runtime/workspace_runtime_projection/` | Move/rename under analysis runtime | #145 | Projection is part of one run capability, not a generic workspace runtime |
| `src/services/history.py` | Move under analysis runtime message repository | #145 | Generic services have no feature owner |
| `src/services/artifact_manager.py` | Move under artifact capability | #145 | Artifact persistence and API projection need one owner |
| Root `src/interface/events/` | Replace with runtime-owned event contract | #145 | Current location mixes wire protocol and LangGraph adapter details |
| `agents/fundamental/subdomains/` | Re-home or delete each module | #145 | Migration-era path; new capabilities belong under owning agent |
| `agents/technical/subdomains/` | Re-home or delete each module | #145 | Migration-era path; new capabilities belong under owning agent |
| API imports of SEC/news/technical private modules | Move behind wiring/facades | #145 | Composition root must not implement capability behavior |
| Agent imports of root `src.services`/`src.interface` implementations | Replace with typed ports/public contracts | #145 | Private cross-slice dependencies increase change blast radius |
| `finance-agent-core/src/agents/ARCHITECTURE_MODULE_ACTIONS.md` stale actions | Regenerate after migration | #145 | Guard report must describe the resulting graph |

## Frontend paths

| Current item | Action | Owner/issue | Reason |
| --- | --- | --- | --- |
| Route components that build API URLs | Move URL construction to feature API modules | #146 | Routes are composition shells |
| `src/lib/auth-api.ts` | Move to `src/features/auth/` | #146 | Auth owns parser and session contract |
| `src/lib/llm-settings-api.ts` | Move to `src/features/llm-settings/` | #146 | Settings feature owns transport |
| `src/lib/search-settings-api.ts` | Move to `src/features/search-settings/` | #146 | Settings feature owns transport |
| `src/components/agent-outputs/*` and `src/types/agents/*` | Move to agent-output feature | #146 | Shared output view owns artifact parser/view model |
| `src/components/technical-observability/*` and related hook/types | Move to observability feature | #146 | Feature owns query parsers and view models |
| Generated `frontend/src/types/generated/api-contract.ts` | Regenerate, never hand-edit | #145/#146 | OpenAPI is the source of truth |
| Old endpoint/event branches and browser compatibility shapes | Delete | #146 | Pre-release cutover has no old client support |
| `Landing*` components with no confirmed product owner | Delete or explicitly retain in inventory | #146 | Every feature needs a current owner |

## Compatibility and dependency rules

- Do not add aliases, dual reads/writes, fallback parsers, migration-only
  facades, old event branches, or feature flags for legacy behavior.
- Do not upgrade LangGraph in #148. Verify any newer typed streaming API in a
  separate dependency gate before adoption.
- Do not copy provider SDK/runtime code into finance-agent-core. Keep LLM
  Provider, Model Inference, and Search behind typed clients.
- Do not close a ledger item by adding an architecture exception. The guard
  must pass after the edge is removed or the documented owner boundary is used.
