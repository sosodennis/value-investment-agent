# Ownership and contract inventory

This is the implementation map for #145 and #146. Current paths are evidence
from baseline `1f9d0745fa0625684c98506c89d750cb8c98161b`; target paths are the
canonical names workers must implement. A target name is one contract owner,
not a compatibility alias.

## Backend capability ownership

| Capability | Current evidence | Canonical owner after cutover | Boundary |
| --- | --- | --- | --- |
| Application composition and lifecycle | `finance-agent-core/api/server.py:125-230` | `finance-agent-core/api/server.py` composition root | FastAPI lifespan, router assembly, dependency wiring, and boundary error mapping only |
| Auth and authenticated principal | `finance-agent-core/src/auth/` and `src/auth/interface/routes.py:24-116` | `src/auth/` | `AuthPrincipal`/`Principal`; browser session and CSRF remain here |
| Analysis/run runtime | `api/server.py:546-1034,1322-1415`; `src/workflow/graph.py`; `src/runtime/workspace_runtime_projection/` | `src/analysis_runtime/` | Start, resume, cancel, snapshot, activity projection, cursor, replay, subscriber delivery |
| Root workflow composition | `src/workflow/graph.py:26-105` | `src/workflow/` composition adapter | Builds graphs through public agent entrypoints; no product event or REST policy |
| Intent agent | `src/agents/intent/entrypoint.py` | `src/agents/intent/` | Intent extraction, ticker search, clarification; public graph entrypoint only |
| Financial news agent | `src/agents/news/entrypoint.py` | `src/agents/news/` | Search, select, fetch, analyse, aggregate; provider I/O stays in infrastructure |
| Debate agent | `src/agents/debate/entrypoint.py` | `src/agents/debate/` | Bull, bear, moderator, evidence and report projection |
| Fundamental agent | `src/agents/fundamental/entrypoint.py` | `src/agents/fundamental/` | Financial health, model selection, parameterization, deterministic valuation |
| Technical agent | `src/agents/technical/entrypoint.py` | `src/agents/technical/` | Market data, features, patterns, regime, fusion, verification, observability inputs |
| Artifact store and API projection | `src/services/artifact_manager.py`; `src/interface/artifacts/`; `api/server.py:1292-1319` | `src/artifacts/` | Artifact persistence, typed artifact references, and `GET /api/v1/artifacts/{artifact_id}` |
| Workflow activity projection | `src/runtime/workspace_runtime_projection/`; `WorkspaceRuntime*` models | `src/analysis_runtime/` activity projection | Owns durable `workflow.activity` records and snapshots; never reads raw frontend shapes |
| Technical observability | `src/agents/technical/subdomains/decision_observability/`; `api/server.py:250-438` | `src/observability/technical/` | DB-backed read model and calibration/monitoring queries |
| LLM settings facade and client | `src/llm_provider/` and `src/llm_provider/composition/routes.py` | `src/llm_provider/` | Browser settings facade plus typed client to independent LLM Provider service |
| Model Inference client | `src/model_inference/` | `src/model_inference/` | Typed inference operation client and trusted internal principal context |
| Search client and settings facade | `src/search/`, `src/search_settings/` | `src/search/` and `src/search_settings/` | Typed Search client; organization-scoped provider settings |
| Shared contracts | `src/shared/kernel/`, `src/shared/internal_services/`, `src/shared/artifacts/` | Same packages, narrowed | Stable domain-neutral contracts only; no feature service or provider policy |
| History messages | `src/services/history.py`; `ChatMessage` in `src/infrastructure/models.py:29-45` | `src/analysis_runtime/` message repository | Thread-owned messages and typed history response |

### Agent entrypoint inventory

| Agent | Public entrypoint | Current graph state | Action |
| --- | --- | --- | --- |
| Intent | `build_intent_extraction_graph` | `agents/intent/workflow/` | Retain public name; remove activity fields through #148/#145 |
| News | `build_financial_news_subgraph` | `agents/news/workflow/` | Retain public name; emit normalized activity through runtime adapter |
| Debate | `build_debate_subgraph` | `agents/debate/workflow/` | Retain public name; model parallel bull/bear activity as a set |
| Fundamental | `build_fundamental_subgraph` | `agents/fundamental/workflow/` plus `subdomains/` | Retain entrypoint; migrate migration-era `subdomains/` ownership under #145 |
| Technical | `build_technical_subgraph` | `agents/technical/workflow/` plus `subdomains/` | Retain entrypoint; migrate migration-era `subdomains/` ownership under #145 |

All agent callers use the public entrypoint or a shared contract. Private
imports from the API composition root, another agent, or migration-era
subdomains are deletion-ledger items even when the architecture guard has no
current exception.

## Frozen public REST contract

The current API has unversioned paths and mixed composition ownership. The
canonical public contract is `/api/v1`, with plural resource names and
lowercase kebab-case segments. The backend owns Pydantic schemas and generated
OpenAPI; the frontend consumes generated types and feature parsers.

| Capability | Canonical method and path | Current path(s) | Owner |
| --- | --- | --- | --- |
| Health | `GET /health` | `/health` | Composition root/operations |
| Readiness | `GET /ready` | `/ready` | Composition root/operations |
| Auth | `POST /api/v1/auth/register`; `POST /api/v1/auth/login`; `GET /api/v1/auth/me`; `POST /api/v1/auth/logout` | `/api/auth/*` | Auth |
| Thread snapshot | `GET /api/v1/threads/{thread_id}` | `/thread/{thread_id}` | Analysis runtime |
| Thread messages | `GET /api/v1/threads/{thread_id}/messages` | `/history/{thread_id}` | Analysis runtime |
| Start/resume run | `POST /api/v1/threads/{thread_id}/runs` | `POST /stream` | Analysis runtime |
| Cancel run | `POST /api/v1/threads/{thread_id}/runs/{run_id}/cancel` | No dedicated route; task cancellation is in `api/server.py` | Analysis runtime |
| Activity snapshot/history | `GET /api/v1/threads/{thread_id}/activities` | `/thread/{thread_id}/activity` | Analysis runtime |
| Activity/event stream | `GET /api/v1/threads/{thread_id}/events` with `after_seq` cursor | `/stream/{thread_id}` | Analysis runtime |
| Agent output status | Included in thread snapshot/activity view | `/thread/{thread_id}/agents` | Analysis runtime; delete standalone compatibility view |
| Artifact | `GET /api/v1/artifacts/{artifact_id}` | `/api/artifacts/{artifact_id}` | Artifact store |
| LLM provider keys | `GET/POST /api/v1/llm/provider-keys`; `POST /api/v1/llm/provider-keys/{key_id}/replace`; `POST /api/v1/llm/provider-keys/{key_id}/test`; `DELETE /api/v1/llm/provider-keys/{key_id}` | `/api/llm/provider-keys*` | LLM settings facade |
| LLM settings | `GET/PUT /api/v1/llm/settings` | `/api/llm/settings` | LLM settings facade |
| Search settings | `GET/PUT /api/v1/search/settings` | `/api/search/settings` | Search settings facade |
| Search provider keys | `POST /api/v1/search/settings/keys`; `PUT/DELETE/PATCH /api/v1/search/settings/keys/{key_id}` | `/api/search/settings/keys*` | Search settings facade |
| Technical observability | `/api/v1/observability/monitoring/{aggregates,rows,events/{event_id}}`; `/api/v1/observability/calibration/direction-readiness` | `/api/observability/*` | Technical observability |

The `thread_id` is the browser-visible thread identity. A `run_id` identifies
one execution attempt within that thread. Ownership is checked before reading
the thread, replaying events, or registering an SSE subscriber; cross-user
resources use the same safe not-found response.

## Frozen event and error vocabulary

The current adapter emits `content.delta`, `agent.status`,
`agent.lifecycle`, `state.update`, `interrupt.request`, and `error` from
`src/interface/events/adapters.py`. The new public activity event is
`workflow.activity`, owned by #148. It carries the stable envelope:

```text
event_id, seq_id, event_version, thread_id, run_id, occurred_at, event_name,
payload
```

`payload` is the typed activity object from #148: `activity_id`, optional
`parent_activity_id`, `scope_path`, `kind`, `status`, `label`, optional measured
`progress`, and `attempt`. Raw LangGraph namespaces, callback metadata, state
dictionaries, `current_node`, and `node_statuses` never cross the application
boundary.

Transient model output remains a separate typed content event. It is not an
activity status and it does not mutate the activity set. Stable error codes
are namespaced lowercase values such as `thread_not_found`,
`run_not_found`, `replay_gap`, `subscriber_overloaded`, `invalid_cursor`,
`run_cancelled`, and `provider_unavailable`. HTTP status mapping belongs to
the API boundary; provider and LangGraph exception text never crosses it.

## Persistence inventory and fresh baseline

| Current table | Current model | Action | Canonical owner |
| --- | --- | --- | --- |
| `llm_settings` | `LlmSetting` | Retain/rebuild with verified organization ownership | LLM settings facade/service |
| `chat_history` | `ChatMessage` | Retain/rebuild as thread message repository; add explicit ownership through thread/run boundary | Analysis runtime |
| `artifacts` | `Artifact` | Retain/rebuild with typed artifact references and owner checks | Artifact store |
| `technical_prediction_events` | `TechnicalPredictionEvent` | Retain for technical observability | Technical observability |
| `technical_outcome_paths` | `TechnicalOutcomePath` | Retain for technical observability | Technical observability |
| `technical_approved_label_snapshots` | `TechnicalApprovedLabelSnapshot` | Retain for technical observability | Technical observability |
| `workspace_runtime_activity_events` | `WorkspaceRuntimeActivityEvent` | Replace with the #148 durable activity event projection; no legacy column compatibility | Analysis runtime |
| `workspace_runtime_activity_segments` | `WorkspaceRuntimeActivitySegment` | Delete; its scalar `agent_id`/`node` segment is not a nested activity model | Analysis runtime |
| `workspace_runtime_run_statuses` | `WorkspaceRuntimeRunStatus` | Replace with typed run lifecycle projection tied to `thread_id` and `run_id` | Analysis runtime |
| `workspace_runtime_cursors` | `WorkspaceRuntimeCursor` | Replace with atomic event/cursor write in the runtime repository | Analysis runtime |

The acceptance database starts empty and is created from the target metadata.
No old rows, checkpoints, migration readers, or dual writes are required.

## Service-client boundaries

| Client | Current evidence | Canonical owner and contract |
| --- | --- | --- |
| LLM Provider | `src/llm_provider/infrastructure/remote_client.py`; `src/llm_provider/domain/contracts.py` | `LLMProviderClient`; operation schemas `provider.v1`/completion and settings operations; service owns provider credentials/runtime |
| Model Inference | `src/model_inference/infrastructure/http_adapter.py`; `src/model_inference/domain/contracts.py` | `ModelInferenceClient`; operation schemas `inference.v1`; trusted internal principal and one absolute deadline |
| Search | `src/search/client.py`; `src/search/contracts.py`; settings client in `src/search_settings/infrastructure/client.py` | `SearchClient` and `SearchSettingsClient`; operation schemas `search.v1`; service owns external search integrations |

Clients expose typed requests/results/errors to agents and settings use cases.
Provider SDK types, raw HTTP responses, service credentials, and user API keys
remain inside the owning adapter/service.

## Frontend feature ownership

| Feature | Current paths | Canonical target | Owned boundary |
| --- | --- | --- | --- |
| Auth | `app/login`, `app/register`, `components/auth`, `lib/auth-api.ts` | `src/features/auth/` | Auth API parser, session state, protected route, login/register |
| Workspace/run | `app/workspace`, `hooks/useAgent*`, `lib/agent-session-state.ts`, `components/workspace` | `src/features/workspace/` | Thread/run API, snapshot parser, activity reducer, SSE recovery, activity UI |
| Agent outputs | `components/agent-outputs`, `types/agents` | `src/features/agent-outputs/` | Typed artifact/preview parsers and agent-specific view models |
| LLM settings | `app/settings/llm`, `lib/llm-settings-api.ts` | `src/features/llm-settings/` | Provider-key and selected-model API/parser/forms |
| Search settings | `app/settings/search`, `lib/search-settings-api.ts` | `src/features/search-settings/` | Provider preferences/key API/parser/forms |
| Technical observability | `app/technical-observability`, `hooks/useTechnicalObservability`, `types/technical-observability`, `components/technical-observability` | `src/features/technical-observability/` | Monitoring/calibration query parsers and view models |
| Navigation and shared UI | `components/global-nav`, `components/beui`, `globals.css` | `src/components/` and `src/lib/` | UI primitives only; no API paths or backend-shape guessing |
| Landing | `components/landing`, `app/page.tsx` | `src/features/landing/` or remove if no current product owner | Only retained if the product owner confirms the route |

Every browser boundary parses `unknown` into a feature view model. Components
never construct URLs, read raw REST/SSE payloads, or infer a current node from
event order. Generated contract files remain outputs of backend OpenAPI.

## Current private-edge inventory

The baseline `python3 scripts/architecture_guard.py` reports zero violations,
but the current composition still imports implementation details that the
target map assigns to a capability boundary:

| Edge | Evidence | #145 action |
| --- | --- | --- |
| API imports SEC XBRL infrastructure directly | `api/server.py:35-38` | Move readiness/close behavior behind the owned fundamental or runtime wiring port |
| API imports news shared HTTP client directly | `api/server.py:39-40` | Close through the news application wiring boundary |
| API imports technical observability subdomain | `api/server.py:40-43,246-438` | Register a technical observability router/facade at composition root |
| Agent repositories import root `src.services` and `src.interface` modules | e.g. `agents/news/infrastructure/artifacts/news_artifact_repository.py`, `agents/debate/infrastructure/artifacts/*`, technical use cases | Move stable artifact/event contracts to owned public ports; delete private root imports as callers migrate |
| Fundamental/technical code imports migration-era `subdomains/` | `agents/fundamental/subdomains/`, `agents/technical/subdomains/` | Re-home under agent capabilities or delete; no new subdomain imports |

The guard result is a baseline fact, not permission to preserve these edges.
The deletion ledger gives the concrete migration action and owner.
