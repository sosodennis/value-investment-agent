# Backend engineering guide

Date: 2026-10-24 | Status: Canonical | Scope: `finance-agent-core/`, `llm-provider-service/`, `model-inference-service/`, and `search-service/`

This guide defines backend ownership, contracts, naming, resource lifecycle, errors, tests, and SSE behavior. Service-specific contracts and runbooks add operational detail. They do not replace these cross-project rules.

## 1. Set ownership by feature

- Organize backend code by vertical slice. A slice owns its public entrypoint, API schemas, use cases, domain rules, adapters, and tests where those responsibilities exist.
- Keep layers inside a slice only when each layer has a real owner responsibility. A small feature does not need empty `domain`, `application`, or `infrastructure` packages.
- Keep the root workflow and FastAPI application as composition roots. They assemble feature entrypoints and resources; they do not reach into private feature modules to implement behavior.
- Keep finance-agent core logic in the backend. Keep LLM Provider, Model Inference, and Search as separate deployable services because they own different provider credentials, model runtime, external search integrations, scaling, and resource lifecycles. Do not make every feature a network service.
- Keep Auth as a backend feature for now. Share only the authenticated principal and the minimum internal-service context needed by downstream services. A separate identity service is a later architecture decision.
- Put code in `shared/` only when more than one feature needs the same stable, domain-neutral contract. Service operation schemas, provider choices, and feature policy stay with their owners.
- Do not split a module to meet a line-count target. Split it when the new boundary makes ownership, dependencies, testing, or change review clearer.

Agent-specific graph and dependency rules are defined by the [Agent Architecture Standard](../.agents/skills/architecture-standard-enforcer/references/cross-agent-architecture-standard.md). The [cross-agent refactor playbook](../finance-agent-core/docs/standards/refactor_lessons_and_cross_agent_playbook.md) records implementation lessons. Do not copy those rules into a second standard.

## 2. Name code and contracts consistently

| Item | Convention | Example |
| --- | --- | --- |
| Python packages, modules, functions, variables, and database columns | `snake_case` | `search_provider.py`, `load_context` |
| Classes, exceptions, and Pydantic models | `PascalCase` | `OpenRouterClient`, `SearchRequest` |
| Fixed module constants | `UPPER_SNAKE_CASE` | `DEFAULT_TIMEOUT_SECONDS` |
| HTTP path segments | Lowercase `kebab-case`; plural resource names | `/api/v1/search-providers` |
| Public JSON fields and timestamps | `snake_case`; timestamps end in `_at` and carry a UTC offset | `created_at: "2026-10-24T12:00:00Z"` |
| Stable event names and error codes | Lowercase namespaced values | `content.delta`, `provider_unavailable` |
| Tests | Name the behavior or boundary | `test_replays_persisted_events_after_cursor` |

Use role suffixes consistently:

- `Provider` adapts one upstream source.
- `Client` owns a transport boundary.
- `Repository` reads or writes persistence.
- `Service` coordinates a use case or multi-owner operation.
- `Policy` owns deterministic decisions.
- `Mapper` transforms one shape into another.
- `Factory` assembles dependencies.
- `Port` names a protocol or interface, never a concrete class.

Annotate every function signature. Do not use `Any` in production code. Keep untyped values at decoding boundaries, validate them there, and pass typed values to use cases. Avoid catch-all modules such as `helpers.py`, `tools.py`, and `services.py` when a feature or role can own the code directly.

Keep one stable identifier for each concept. Agent IDs, artifact kinds, output kinds, workflow node IDs, and display labels have different jobs and must not be inferred from one another.

Existing public field and route names remain part of their contracts. Use `snake_case` for new JSON fields. When correcting an existing contract, update the backend schema, OpenAPI, generated client types, frontend parser, service clients, fixtures, and tests in one change. This project is pre-release, so remove obsolete aliases after all in-repository callers move.

## 3. Version public and internal contracts

- Put public REST and SSE routes under `/api/v1`. Use lowercase plural resources and `kebab-case` path segments. Use an action subpath only when the operation is a command rather than resource CRUD.
- Before the first public release, move existing unversioned routes to `/api/v1` in a coordinated backend, frontend, OpenAPI, and test change. Remove the old paths in the same cutover.
- Keep additive, optional changes in the current major version. Put incompatible request, response, or event changes under a new major version such as `/api/v2`.
- Treat the URL major version as the public API contract version. Do not use query parameters or headers to select a different public contract version.
- Give SSE payloads an explicit event schema version. A route version does not version LangGraph state or internal event formats.
- Keep internal service versions independent from the public API. `internal.v1` versions shared request context; each service operation owns its own schema version, such as `search.v1` or `inference.v1`.
- Add fields compatibly within a service operation version. Bump that operation's version when its required input, result shape, or error semantics change incompatibly.

## 4. Keep API and service contracts explicit

- Define HTTP request and response bodies with Pydantic v2 models. Use `model_dump()` and `model_validate()` at the boundary.
- Treat OpenAPI as the source for generated frontend API types. Run `bash scripts/generate-contracts.sh` from the repository root after an API change.
- Keep HTTP adapters responsible for parsing, authentication, serialization, and mapping typed failures to HTTP responses. Use cases must not depend on FastAPI request objects or response classes.
- Keep public API schemas separate from database models and third-party SDK types.
- Give each internal service ownership of its operation request, result, and error codes. `internal.v1` versions shared caller context such as principal, correlation ID, and deadline; an operation schema such as `search.v1` has its own lifecycle.
- Derive a downstream `subject_id` from the authenticated principal. Never accept it as authority from a browser body, query, or header.
- Send one absolute deadline through the service call chain. Each client uses the remaining budget instead of resetting the timeout at every hop.
- Keep routes and error responses stable. Document pagination, empty versus missing values, identifiers, timestamps, and retryability in the owning schema.

The [internal capability service contract](../finance-agent-core/src/shared/internal_services/README.md), [LLM Provider contract](llm-provider-contract.md), [Search contract](search-service-contract.md), and [Inference contract](issue-121-inference-boundary.md) define their service-specific wire shapes.

## 5. Manage asynchronous work and resources by lifecycle

- Use FastAPI lifespan to create and close process-scoped clients, database engines, checkpointers, and service connections.
- Reuse an `httpx.AsyncClient` or provider SDK client across requests. Do not build one client per event, article, or model call.
- Create one SQLAlchemy `AsyncSession` per concurrent task or transaction. Never use one session from multiple tasks at once.
- Prefer native async I/O. If a required SDK exposes only synchronous I/O, offload it at the adapter boundary. Do not block the event loop with a network call or heavy computation.
- Bound fan-out concurrency, queues, response size, and expensive computation. A semaphore or worker limit must reflect measured provider and deployment capacity.
- Apply connect, read, and total deadlines. Cancel downstream work when the caller cancels unless the operation has an explicit durable background-job lifecycle.
- Retry only classified transient failures, within the original deadline, and only when the operation is safe to repeat or has an idempotency key. Keep retry ownership in one layer.

## 6. Separate workflow state from product events

LangGraph state and checkpoints serve graph execution and resume. Product activity, status, and event projections serve the UI and query APIs. Keep their schemas and retention policies explicit.

The analysis runtime keeps the latest `workflow_runs` row for active-run coordination and stores durable per-run history in `workflow_run_history`, keyed by `(thread_id, run_id)`. The database migration service creates the schema and runs a versioned, resumable legacy-history backfill in bounded batches before the API starts. API startup fails fast while that migration is incomplete; process restarts do not rescan activity history. Legacy inputs that were not stored remain null; a legacy run without a matching run row has `started_at: null`, and a status without a terminal event or matching run row is `unknown`. Rows without an authoritative thread owner are not assigned to a user. Run `uv run python -m src.infrastructure.migrations.cli` before starting the API outside Compose.

- Keep LangGraph internal event shapes behind an adapter. Map them to stable application event contracts before sending them to the browser.
- Keep checkpoint state limited to orchestration data and references needed to resume. Store large report payloads in artifacts and expose typed previews or references.
- Make state readers tolerant of absent optional fields. Convert untrusted workflow state into typed values at the node or adapter boundary.
- Represent missing artifacts as `not_found`, distinct from valid empty results.
- Test graphs through their public entrypoints with fake adapters. Test the root composer with fake compiled graphs.

The locked LangGraph version is the supported API. Check its version-specific documentation before adopting APIs described only for a newer release.

## 7. Define SSE as a recoverable event contract

The transport recommendation is browser to FastAPI. Do not add a Next.js proxy only to make SSE work. Transport success does not prove authorization, replay, or multi-worker delivery.

### Event and cursor rules

- Use a stable, versioned application event envelope. Include the event ID or sequence, event name, `thread_id`, `run_id`, and typed payload.
- Keep event names stable and namespaced. Do not derive public event names from LangGraph node names.
- Define delivery as at-least-once and deduplicate by event ID. The client must reject events for a different thread or run.
- Advance a durable cursor only after the corresponding event is persisted. Persist event data and cursor state atomically.
- Persist replayable `content.delta` events as well as lifecycle events. Coalesce high-frequency deltas before persisting them; never advance the durable cursor past an event that replay cannot restore.
- Return a resume cursor when a run starts or resumes. Attach and reconnect from the last event the client applied.
- Retain replayable SSE events for 24 hours by default. Make retention, maximum replay count, and maximum replay bytes configurable and bounded. This event-log TTL does not delete run records, LangGraph checkpoints, or final artifacts; each has its own retention policy.
- Bound each replay response by 200 events or 1 MiB, whichever comes first, unless deployment configuration sets a lower limit. If the cursor predates retained data or exceeds replay limits, return an explicit `replay_gap` result and let the client hydrate `GET /thread/{thread_id}`, which is the snapshot recovery endpoint. The snapshot includes the current cursor and run state. The client then attaches after that cursor; never imply that a truncated replay is complete.
- Subscribe and replay without a gap. Deduplicate events that appear in both paths and test the race between live publication and replay.

### Ownership, backpressure, and cancellation

- Check thread ownership before registering a subscriber or reading replay data.
- Give each subscriber a bounded queue, with an initial default of 256 queued messages. If a subscriber falls behind, close that subscription with a typed `subscriber_overloaded` outcome. The client reconnects from its last applied cursor.
- A subscriber disconnect does not cancel a run. The run continues in the current backend process until terminal state or explicit user cancellation. Process restart survival is not guaranteed until durable run execution is implemented.
- Close generators, queues, tasks, and upstream streams on disconnect, cancellation, terminal event, and application shutdown.
- Run one API worker process per container by default. Do not increase Uvicorn's worker count to improve LangGraph concurrency; async I/O already serves concurrent requests, while additional processes cannot share process-local run state or subscriber queues.
- Keep run IDs, event cursors, and stream contracts independent of the worker that handles a request. Do not rely on sticky sessions to provide correctness across reconnects or process restarts.
- Process-local queues support one worker only. Do not claim multi-worker or multi-replica delivery until run state, shared fan-out, and durable replay pass integration tests across workers. Issue [#147](https://github.com/sosodennis/value-investment-agent/issues/147) tracks the shared delivery and final cutover gate under the full-stack refactor epic [#143](https://github.com/sosodennis/value-investment-agent/issues/143).

### HTTP and deployment behavior

- Send `Content-Type: text/event-stream` and disable response caching.
- Send an SSE heartbeat every 15 seconds by default. Make the interval configurable and keep it below the shortest idle timeout in the deployed request path.
- A proxy idle/read timeout limits how long the proxy waits without receiving another upstream byte; it is not the maximum allowed duration of the whole run. Set it longer than the heartbeat interval with operational margin. If traffic passes through NGINX, disable proxy buffering for the SSE route.
- If traffic uses a Next.js rewrite, send `Cache-Control: no-cache, no-transform` and test the exact deployed path. Do not rely on one header to configure every CDN or ingress product.
- During local development, validate the direct browser-to-FastAPI path with event IDs, timestamps, heartbeats, terminal events, and a forced disconnect/reconnect. Defer the production ingress, proxy, and CDN smoke test until the deployment path exists; local results do not establish production behavior.
- Issue [#145](https://github.com/sosodennis/value-investment-agent/issues/145) tracks moving run and stream orchestration out of `api/server.py` as part of the canonical backend reset. Keep that refactor aligned with the event contract instead of making a second SSE abstraction.

The current implementation audit in [Discussion #131](https://github.com/sosodennis/value-investment-agent/discussions/131) supports direct browser-to-FastAPI transport. It also documents the difference between transport behavior, user ownership, durable replay, and multi-worker support. The full-stack reset is tracked by [#143](https://github.com/sosodennis/value-investment-agent/issues/143): backend runtime, ownership, and local replay are owned by [#145](https://github.com/sosodennis/value-investment-agent/issues/145), frontend recovery by [#146](https://github.com/sosodennis/value-investment-agent/issues/146), and shared delivery/final cutover by [#147](https://github.com/sosodennis/value-investment-agent/issues/147).

## 8. Handle errors and observe behavior safely

- Raise typed application errors for expected failures. Map them to stable error codes at HTTP and service boundaries.
- Do not return stack traces, provider exceptions, internal URLs, prompts, article text, session credentials, or API keys to clients or logs.
- Log structured events with stable names and bounded fields. Include operation, correlation ID, duration, outcome, retry count, and degradation reason where relevant.
- Log both success and every terminal failure or degraded outcome. Avoid duplicate success logs for each item in a high-volume loop.
- Keep prompts, financial data, user identifiers, and secrets out of metric labels. Redact sensitive values before logging.
- Propagate correlation IDs across internal services. Keep the service credential in the authorization header, separate from user principal context.

## 9. Test behavior at each boundary

Add tests at the boundary that owns the behavior:

- Unit-test deterministic domain policies without network or database dependencies.
- Test use cases with fake ports and test provider adapters with controlled HTTP responses.
- Validate request and response contracts on both sides of every internal service call.
- Test database ownership, transaction boundaries, missing-versus-empty values, and concurrent session usage.
- Test cancellation, deadlines, retry limits, partial provider failures, and redaction.
- Test SSE authorization, event ordering, cursor replay, replay/live races, gaps, duplicate delivery, slow consumers, and disconnect cleanup.
- Test agent architecture rules with `python3 scripts/architecture_guard.py` from the repository root.

Run focused tests first, then the relevant service suite. The backend test command is `uv run pytest` from `finance-agent-core/`. Run Ruff checks for changed Python packages when the project configuration applies.

## 10. Current module alignment snapshot

This table records the 2026-10-24 code and issue review. It is an audit snapshot, not a substitute for GitHub issue status. The detailed research is in [Discussion #140](https://github.com/sosodennis/value-investment-agent/discussions/140).

| Feature or module | Action | Target and validation |
| --- | --- | --- |
| `api/server.py` and application composition | Refactor | Keep app lifespan and router assembly at the composition root. Move run policy and stream delivery behind owned modules. Track with [#145](https://github.com/sosodennis/value-investment-agent/issues/145). |
| Agent slices and root workflow | Align | Use public agent entrypoints and shared contracts. Keep the architecture guard and module action report current. |
| Auth and run ownership | Verify | Enforce the same owner check for REST, artifacts, and SSE attach before reading or registering resources. The backend cutover and ownership checks are part of [#145](https://github.com/sosodennis/value-investment-agent/issues/145). |
| LLM Provider facade and service | Align | Separate the agent-facing client, product settings facade, and provider runtime. Keep provider SDK types in its adapter and test service lifecycle and retry ownership. |
| Model Inference client and service | Align | Bound model concurrency, deadlines, cancellation, and blocking work. Keep domain-specific fallback in the caller that owns the decision. |
| Search client, settings, and service | Align | Keep provider response types inside provider adapters. Normalize search results before returning them to agents and preserve user scoping for keys and preferences. |
| `shared/internal_services` | Keep narrow | Share principal, correlation, deadline, authentication, error, and readiness primitives. Keep every operation schema with its service. |
| LangGraph checkpoint and runtime projection | Align | Keep graph resume state separate from durable product events and read projections. Define retention for each store. |
| HTTP and internal-service contracts | Align | Use explicit Pydantic schemas, generated OpenAPI types, stable error codes, UTC timestamps, and operation-specific schema versions. |
| SSE replay and fan-out | Refactor | Run one API worker per container by default. Complete local replay, snapshot recovery, reconnect, and bounded queues under [#145](https://github.com/sosodennis/value-investment-agent/issues/145). Use PostgreSQL as the durable event source and test shared run state and delivery across workers under [#147](https://github.com/sosodennis/value-investment-agent/issues/147) before claiming horizontal scale. Keep the notification mechanism behind an adapter. |
| Tests and telemetry | Extend | Cover ownership, contract drift, partial failures, deadlines, redaction, replay, and disconnect behavior at the owning boundary. |

## 11. External references

- [PEP 8](https://peps.python.org/pep-0008/) defines Python naming and formatting conventions.
- [FastAPI: Bigger Applications](https://fastapi.tiangolo.com/tutorial/bigger-applications/) documents router composition.
- [FastAPI: Lifespan Events](https://fastapi.tiangolo.com/advanced/events/) documents application-scoped resource setup and cleanup.
- [Pydantic models](https://docs.pydantic.dev/latest/concepts/models/) documents validation and serialization.
- [SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#using-asyncsession-with-concurrent-tasks) explains why concurrent tasks need separate `AsyncSession` instances.
- [LangGraph streaming](https://docs.langchain.com/oss/python/langgraph/streaming) and [persistence](https://docs.langchain.com/oss/python/langgraph/persistence) describe graph streaming and checkpoint behavior.
- [PostgreSQL LISTEN](https://www.postgresql.org/docs/16/sql-listen.html) and [NOTIFY](https://www.postgresql.org/docs/16/sql-notify.html) document the local notification adapter; the event table remains the durable source.
- [WHATWG Server-sent events](https://html.spec.whatwg.org/multipage/server-sent-events.html) defines framing, event IDs, and reconnect semantics.
- [NGINX proxy buffering](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_buffering) documents one common proxy's stream behavior.
- [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/instrumentation/) describes trace and span instrumentation.
- Community comparisons include [FastAPI Best Architecture](https://github.com/fastapi-practices/fastapi-best-architecture) and the [FastAPI full-stack template](https://github.com/fastapi/full-stack-fastapi-template). Treat them as examples, not project rules.
