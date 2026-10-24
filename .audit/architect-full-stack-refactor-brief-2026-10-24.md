# Architect Handoff: Full-Stack Refactor Execution

Date: 2026-10-24
Repository: `value-investment-agent`
Baseline: `main` at `80e4a6f`
Execution mode: pre-release hard cutover

This document is the execution brief for the architect who will coordinate two
or three engineers, review their work, and drive the full-stack refactor to a
mergeable and independently verified result.

## Mission

Complete the backend and frontend architecture reset under epic [#143](https://github.com/sosodennis/value-investment-agent/issues/143), including the canonical nested workflow activity contract, backend run/SSE runtime, frontend workflow consumer, and shared-worker integration.

The finished system must have explicit capability ownership, typed contracts,
durable replay, authenticated resource ownership, parser-first frontend
boundaries, and no obsolete compatibility paths. The architect is accountable
for the final result. Engineer reports are evidence to inspect, not acceptance
by themselves.

## Hard cutover rules

- The project is pre-release. Do not preserve old clients, old routes, old event names, old database contents, old checkpoints, old module paths, or old payload shapes.
- Do not add compatibility aliases, dual reads/writes, fallback parsers, migration-only facades, or feature flags whose purpose is to keep the old design alive.
- Delete APIs that have no current owner or product use. Rename inaccurate concepts directly. Replace poor contracts instead of wrapping them.
- Rebuild the database and fixtures from the new schema. Fresh database setup is the acceptance baseline; no legacy migration is required.
- Migrate every caller and delete the old path in the same cutover. A stale import, route, event branch, generated contract, table, column, or parser is a failure.
- Keep independent capability services independent. Finance-agent-core owns financial policy and LangGraph workflow composition; LLM Provider, Model Inference, and Search remain behind typed internal clients.
- A repeated workaround is an architecture signal. After two unrelated deviations or special cases of the same shape, stop, re-run `how`, and redesign from first principles before adding more patches.

## Delivery graph and worker plan

The canonical dependency graph is:

```text
#144 ownership and contract inventory
                 |
#148 workflow.activity protocol and fixtures
                 |
        +--------+--------+
        |                 |
   #145 backend       #146 frontend
        |                 |
        +--------+--------+
                 |
          #147 integration
```

Use at most two implementation workers in parallel and one integration owner.
The recommended assignment is:

| Worker | Issue(s) | Owns | Must not edit |
| --- | --- | --- | --- |
| Engineer A, `gpt-6.1-sol` high | #144, then #148 | `docs/` inventory, naming matrix, deletion ledger, activity contract, fixtures | backend source, frontend source, service implementations, lockfiles |
| Engineer B, `gpt-6.1-sol` high | #145 | `finance-agent-core/**`, generated backend OpenAPI output, backend fixtures | `frontend/**`, standalone capability-service implementations, Compose orchestration |
| Engineer C, `gpt-6.1-sol` medium or high | #146 | `frontend/**`, excluding dependency manifests owned by #104 | backend source, service implementations, Compose files |
| Architect or integration owner, `gpt-6.1-sol` high | #147 | root verification scripts, Compose/test orchestration, explicitly handed-off cross-worker adapter, final report | feature source owned by B or C, standalone service business logic |

Engineer A must finish and publish #144 before freezing #148. B and C may
start only after the architect accepts the #148 fixtures and handoff. B and C
can then work in parallel because their write ownership is disjoint. #147 waits
for both implementation branches and performs the final cutover.

Do not give two workers ownership of a shared contract file. If a contract
change is required after handoff, the architect stops both consumers, records
the decision, assigns the change to Engineer A or the architect, regenerates
fixtures, and re-runs the affected gates before work resumes.

## Worktree and branch protocol

Start every worktree from a clean, current `main`. Use one branch and one
directory per worker:

```text
codex/refactor-contract-a
codex/refactor-backend-b
codex/refactor-frontend-c
codex/refactor-integration
```

The architect must record each worktree path, base SHA, branch SHA, and file
ownership in the handoff log. Workers must rebase onto the accepted contract
handoff before opening a PR. Never make concurrent edits in one checkout.

The architect merges in this order:

1. Engineer A's #144 and #148 contract branch.
2. Engineer B's #145 backend branch and Engineer C's #146 frontend branch, in either order after both have consumed the same fixtures.
3. The integration branch for #147, followed by a clean checkout verification against the resulting `main`.

No issue is closed because a PR was opened or because a worker says it is
finished. Close an issue only after the architect has inspected the merged
diff, rerun the relevant checks, and recorded a `VERIFIED` verdict.

## One-time human staging gate

The architect must put this gate before the first LLM-dependent acceptance
step. It is the only expected human setup action during the run:

1. Start the required local stack and make the login, registration, and LLM settings pages reachable.
2. Give the human the exact local URL and ask them to create a dedicated staging account through `/register`.
3. Ask the human to sign in and add a disposable OpenRouter key at `/settings/llm`, using the labels in the LLM prerequisite section below.
4. Ask the human to reply only that the account and key have been provisioned. The architect's staging smoke command performs the actual key test. Never ask for the password, session cookie, raw key, or an authorization header in chat, issues, or reports.
5. Continue all non-LLM checks while the human is completing this step. Once the human confirms provisioning, run the LLM-dependent browser and integration gates and record only masked metadata and request evidence.

If the execution environment supports an architect-controlled browser session,
the human may complete these steps in that session so the architect can use the
already-authenticated browser without receiving credentials. Otherwise the
architect must use the project's approved local secret mechanism for a
dedicated test credential; credentials must remain untracked and must never be
printed in reports or commands.

The user session is browser-local. A login in the human's browser is not
automatically available to another browser, worktree, or API client. The human
can still test the running application independently in another browser or
account. Do not have two people concurrently add, replace, or delete keys in
the same account's pool because those mutations are intentionally user-scoped
and can race with failover tests. Use a separate manual-QA account and key for
concurrent testing, or limit the human's staging-account use to read-only UI
inspection while the architect runs the mutation and failover matrix.

### Shared staging access for engineers

The architect must make staging access repeatable without asking the human to
retest the key on every branch or rebuild:

- Keep one explicitly named shared staging Compose project for live LLM smoke and integration checks. It owns the staging database, LiteLLM state, Redis coordination, and provider service. Do not point every feature worktree at the same mutable database.
- Add an idempotent root script under the #147 integration ownership, such as `scripts/refactor_staging_smoke.sh`. It must validate service health, register-or-login the dedicated staging user, ensure the labelled provider key exists when the local secret is available, call the authenticated provider test/completion path, and print only masked status, request IDs, latency, attempt count, and provider error codes.
- The script reads secrets from an untracked local secret source (the existing ignored `.env` for local development or an approved OS secret store). At minimum define `STAGING_BASE_URL`, `STAGING_EMAIL`, `STAGING_PASSWORD`, and `STAGING_OPENROUTER_KEY`; optionally define `STAGING_PRIMARY_LABEL` and `STAGING_SECONDARY_LABEL` when an existing pool uses different labels. Service tokens such as `LITELLM_MASTER_KEY` and `LLM_PROVIDER_SERVICE_TOKEN` are injected separately by Compose. Never echo the values, include them in command output, or write them to a report.
- `STAGING_BASE_URL` is required per worktree and is not a repository-wide constant. When the script runs on a host, set it to that Compose project's published FastAPI origin, for example `http://127.0.0.1:8100` for the current shared staging project or `http://127.0.0.1:8000` for a worktree that selected the default port. Do not use the frontend origin, do not append `/api`, and do not add a trailing slash. A script running inside Compose uses the service DNS origin such as `http://backend:8000`. The script must fail fast on a missing or unhealthy base URL instead of guessing another worker's port.
- The script must be safe to rerun after a fresh database: registration conflicts become login, key creation is keyed by the explicit label, and a failed test does not create duplicate records. Raw key material is sent only through the authenticated settings/provider path and is never stored in project application metadata.
- Engineers use this command for real-provider checks and use fake providers or contract fixtures for ordinary unit and feature development. Only the architect/integration owner mutates the shared staging pool during the failover matrix; other engineers may run bounded read/test requests but must not add, replace, or delete its keys concurrently.
- If a separate worktree needs live LLM calls, it must use its own Compose project, ports, database, and credentials, or run against the shared staging project in read/test-only mode. A worktree must never silently reuse another worktree's volumes.

This removes the need for the human to participate in routine provider tests.
The human provisions the account and secret once; the architect and engineers
run the repeatable command thereafter. If the local secret source is not
available, continue with fake-provider and contract gates and mark live LLM
acceptance `INCONCLUSIVE` rather than asking for a key in chat.

## Required pstack workflow

Every worker and the architect must follow the repository `AGENTS.md` and use
the pstack workflow. The architect enforces these phases:

1. **Ground.** Use `how` to map the touched subsystem and `why` when changing ownership or layering. For agents, use `agent-implementation-extractor`; for failure or regression work, use `agent-debug-review-playbook`.
2. **Sketch.** Use `architect` before implementation. Write the type shapes, ports, module boundaries, ownership, and error contracts. For a major boundary, compare at least two structurally different candidates and record the selection.
3. **Execute in units.** Use `principle-sequence-verifiable-units`: one coherent change, one focused check, then move forward. Use `principle-separate-before-serializing-shared-state` to eliminate concurrent writes before adding locks or conventions.
4. **Review.** Apply `architecture-standard-enforcer`, `typescript-best-practices` for TypeScript work, and the relevant boundary/concurrency/error-handling guidance. The architect performs an independent review of each PR.
5. **Prove.** Use `principle-prove-it-works` against the real stack. A compile-only result, a worker's self-report, a cached screenshot, or a test that never exercises the new contract is not acceptance.
6. **Scrap when needed.** If implementation repeatedly needs escape hatches, casts, compatibility branches, or caller knowledge of private rules, stop and return to the sketch. Do not hide architectural failure inside more adapters.

Use `figure-it-out` for the overall run and keep a decision trail. A verdict
must be one of `VERIFIED`, `NOT VERIFIED`, or `INCONCLUSIVE`; `INCONCLUSIVE`
is not a pass.

## Contract target

`internal_progress` is deleted from root and subgraph state. The public runtime
activity contract is the typed `workflow.activity` event defined by #148:

- `activity_id`, `parent_activity_id`, `thread_id`, and `run_id` are stable identities.
- `scope_path` is an application scope path, not a raw LangGraph namespace.
- `kind` is `phase`, `node`, `tool`, or `subgraph`.
- `status` is `queued`, `running`, `waiting`, `completed`, `failed`, `cancelled`, or `skipped`.
- `progress` is optional and must be in `[0, 100]`; parallel work is an activity set and never a guessed aggregate percentage.
- `attempt` distinguishes retries or resumed attempts.
- Raw LangGraph namespaces, arbitrary state dictionaries, credentials, prompts, and SDK errors never cross the public boundary.

LangGraph checkpoints remain execution state. They are not the product activity
feed. The backend normalizes supported `custom`, `tasks`, and selected node
boundary signals. Verify any newer typed event-streaming API against the pinned
runtime before adopting it; do not upgrade LangGraph opportunistically inside
#148.

## Issue acceptance gates

### #144: ownership and contract inventory

Engineer A must produce a repository-wide map of backend modules, agent
entrypoints, public routes, SSE events, persistence tables, service clients,
frontend features, and cross-slice imports. Each item gets exactly one
canonical name and owner. The deletion ledger must state whether an item is
deleted, renamed, or retained and why. Baseline architecture checks must run
before implementation. No product code changes belong in this issue.

Architect acceptance requires the map to be specific enough that B and C can
work without guessing.

### #148: canonical nested activity contract

Engineer A must publish the lifecycle table, identity rules, snapshot shape,
SSE envelope, cursor semantics, and fixtures for sequential nodes, parallel
subgraphs, repeated invocations, retries, interrupts, cancellation, failure,
completion, duplicate delivery, replay, and sequence gaps. Fixtures must be
consumable by both backend and frontend without reading `internal_progress` or
private LangGraph metadata.

Architect acceptance requires the old field and event mapping to be explicitly
marked for deletion and the pinned-version implementation path to be stated.

### #145: backend capability slices and runtime

Engineer B must:

- Reduce `finance-agent-core/api/server.py` to lifespan, router assembly, dependency wiring, and boundary error mapping.
- Move graph execution, run lifecycle, event persistence, projection, replay, queue policy, and SSE framing behind owned runtime modules with typed ports.
- Enforce authenticated ownership before thread lookup, replay access, or subscriber registration. Cross-user resources use one safe not-found behavior.
- Persist the normalized event and advance the cursor atomically before publishing SSE. A failed projection write is never reported as durable delivery.
- Implement bounded queues, heartbeat, terminal behavior, cancellation, duplicate suppression, replay limits, `replay_gap`, subscribe/replay race handling, and explicit `subscriber_overloaded` behavior.
- Delete `internal_progress`, root workflow nodes, stale `subdomains/` paths, generic service ownership, private cross-slice imports, old routes, and old event branches assigned to delete.
- Keep Auth, LLM Provider, Model Inference, and Search behind typed clients and trusted internal principal context.

Required evidence includes fresh-database backend tests for ownership, storage
failure, ordering, replay, gaps, duplicate delivery, slow consumers,
cancellation, and terminal events; an architecture guard pass; and generated
OpenAPI output matching the accepted contract.

### #146: frontend feature boundaries and workflow consumer

Engineer C must:

- Make routes thin shells and give Auth, Workspace, LLM settings, Search settings, observability, and agent output explicit feature ownership.
- Parse every external REST/SSE value from `unknown` into a typed view model. Components never guess backend shapes.
- Hydrate a snapshot first, apply only post-cursor deltas, deduplicate event IDs, detect sequence gaps, recover by replay or snapshot, reconnect with bounded backoff, and keep connection state separate from workflow state.
- Render nested activity sets and optional progress without inferring one current node or fabricating parallel percentages.
- Remove old endpoint/event branches, local-storage shapes, duplicate parsers, and unowned components. Apply the adopted BeUI/source component foundation without allowing UI components to define transport contracts.

Required evidence includes valid and malformed payload fixtures, cross-run and
cross-thread rejection, duplicate/gap recovery, reconnect, terminal and
cancellation behavior, loading/empty/stale/error/degraded states, `npm run
lint`, `npm run typecheck`, and the full frontend test command on a fresh
install.

### #147: cross-worker delivery and final cutover

The integration owner must replace process-local live fan-out with the shared
notification adapter handed off by #145. Start with PostgreSQL
`LISTEN/NOTIFY` plus the durable event table; introduce another broker only if
measured load or connection limits require it. Sticky sessions are never a
correctness mechanism.

Run two API workers or replicas and prove live delivery, replay during a live
race, reconnect after disconnect, worker exit recovery, cancellation, cleanup,
bounded queues, and slow-consumer behavior. Run the final stale-path scan for
old routes, events, imports, generated contracts, aliases, obsolete tables and
columns, and architecture exceptions. Use a fresh database and isolated Compose
project. Ingress, CDN, and production proxy validation remain deferred unless a
real deployment path exists.

## LLM prerequisite and what it does not unblock

Before LLM-dependent browser or end-to-end acceptance, the human operator
completes the one-time staging gate above and creates a dedicated staging user
through the normal registration page:

```text
`/register` -> dedicated refactor staging account -> `/settings/llm`
```

Use a disposable, valid OpenRouter key and label it
`full-refactor-staging-primary`. If the failover/recovery matrix is being run,
add a second valid key labelled `full-refactor-staging-secondary`. The key must
be tested successfully through the authenticated settings page. Store the raw
key only in the provider's secret path; the project database and browser should
see only masked metadata, fingerprint, suffix, label, status, and telemetry.

Do not use a shared engineer account, a platform-admin account, a LiteLLM admin
token, or a key pasted into an issue, fixture, screenshot, log, tracked `.env`,
or source file. The user session authenticates the settings page. `LITELLM_MASTER_KEY`
and `LLM_PROVIDER_SERVICE_TOKEN` are deployment-only internal secrets supplied
to Compose through an untracked environment/secret mechanism; they are not
values a browser user enters.

A successful staging key removes only the external OpenRouter credential blocker
for LLM-dependent checks. It does not prove the full refactor or remove blockers
such as an incomplete contract, backend/frontend drift, Docker build failure,
fresh-database failure, non-atomic projection, broken replay, or failed
cross-worker delivery. Non-LLM unit and contract checks should continue while a
key is unavailable.

## Docker and resource protocol

Read and follow `.agents/skills/docker-development/SKILL.md` before changing
Compose, building images, starting services, or cleaning resources.

- Every active worktree uses a unique explicit Compose project name, for example `value-investment-agent-refactor-b`.
- Pass the same `-p` value to every Compose command for that worktree. Use unique host ports and untracked per-worktree env overrides.
- Do not set fixed `container_name`, custom shared volume names, or shared bind-mounted state for concurrent worktrees.
- Validate with `docker compose -p "$PROJECT" config --quiet` and inspect services/profiles before starting anything.
- Start only the services needed for the current gate. Check health with `docker compose -p "$PROJECT" ps` and inspect logs directly.
- Build high-footprint images serially when Docker Desktop disk or memory is under pressure. Keep BuildKit cache enabled; use `docker system df -v` and `docker buildx du --verbose` before pruning.
- Never run global `docker system prune --volumes`, `docker volume prune`, or an unreviewed `docker image prune -a` on the shared engine. Preserve named volumes unless deletion is explicitly part of the disposable fresh-stack gate.
- At worktree completion, verify the project name and use project-scoped cleanup such as `docker compose -p "$PROJECT" down --rmi local`; do not remove shared custom images or volumes.

The Docker Desktop disk image limit is a shared VM capacity, not a quota for
this repository or one worktree. A larger limit helps concurrent engineers but
does not replace project naming, port/volume isolation, selective builds, and
scoped cleanup.

## Required worker report

Each engineer must return a short report containing:

- issue number, branch, worktree, base SHA, result SHA, and exact file ownership;
- the accepted sketch and any deviations, with the decision source;
- commands run and their exit codes, including focused tests and relevant full gates;
- direct evidence for the observable behavior, not just a claim that it passed;
- Docker project name, services used, health status, and cleanup result when applicable;
- `VERIFIED`, `NOT VERIFIED`, or `INCONCLUSIVE` verdict;
- residual gaps, deferred production checks, and any blocker that needs the architect or human operator.

The report must never contain raw API keys, session cookies, passwords, service
tokens, prompts, provider response bodies, or unredacted authorization headers.

## Architect acceptance and merge checklist

Before merging each branch, the architect must inspect the actual diff and
rerun the worker's most important checks from the worker's worktree or a clean
checkout. At the final gate, verify:

- #144 and #148 fixtures are the single contract consumed by both consumers;
- `internal_progress` and all obsolete routes/events/parsers/imports are gone;
- fresh backend and frontend builds start from an empty database;
- authentication and owner checks happen before replay or subscription access;
- event persistence/cursor atomicity, replay, gap recovery, reconnect,
  duplicate handling, bounded queues, heartbeat, cancellation, and terminal
  behavior pass against the real local stack;
- two workers/replicas receive shared events without sticky-session authority;
- service health, generated OpenAPI, backend tests, frontend lint/typecheck/
  tests, service contract tests, architecture guard, and Compose checks pass;
- no issue is marked complete from an inconclusive probe or a cached artifact;
- the final report records exact SHAs, commands, evidence, residual gaps, and
  any intentionally deferred ingress/Agent Server work.

Only after this checklist is `VERIFIED` may the architect merge the PR and close
the corresponding issue. If a gate is `NOT VERIFIED`, keep the issue open and
assign a focused follow-up. If it is `INCONCLUSIVE`, improve the observation
method or test harness; do not reinterpret it as success.
