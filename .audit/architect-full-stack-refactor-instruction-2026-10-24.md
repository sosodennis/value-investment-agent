# Architect Execution Instruction: Complete the Full-Stack Refactor

Date: 2026-10-24
Repository: `value-investment-agent`
Canonical source: this document
Baseline: clean `main` at the current accepted SHA

This instruction replaces the previous architect brief. Use this file as the
single execution authority for the refactor. Do not keep a second plan with a
different dependency order or staging procedure.

## Mission

Coordinate two or three engineers, implement the architecture reset, and drive
it through independent acceptance until the backend and frontend can be merged
as one coherent pre-release cutover.

The result must have explicit capability ownership, typed REST/SSE contracts,
durable workflow activity and replay, authenticated resource ownership,
parser-first frontend boundaries, independent provider services, and no legacy
compatibility paths.

## Non-negotiable cutover policy

- The product is pre-release. Do not preserve old clients, routes, event names, database contents, checkpoints, module paths, or payload shapes.
- Do not add aliases, dual reads/writes, fallback parsers, migration-only facades, or flags whose purpose is to keep the old design alive.
- Delete APIs without a current owner. Rename inaccurate concepts directly. Replace poor contracts instead of wrapping them.
- Rebuild the database and fixtures from the new schema. Fresh database setup is the acceptance baseline; no legacy migration is required.
- Migrate every caller and delete the old path in the same cutover. A stale import, route, event branch, generated contract, table, column, parser, or exception is a failure.
- Keep LLM Provider, Model Inference, and Search as independent services behind typed clients. Finance-agent-core owns financial policy and LangGraph workflow composition, not provider/runtime implementations.
- If the same workaround appears twice in unrelated places, stop and redesign the boundary before adding another patch.

## Required dependency order

```text
#143 epic
  |
#144 ownership and contract inventory
  |
#148 workflow.activity protocol and fixtures
  |
  +-------------------+
  |                   |
#145 backend       #146 frontend
  |                   |
  +-------------------+
          |
        #147 integration and final cutover
```

Never start backend or frontend implementation before #148 is accepted. #145
and #146 may then run in parallel because they have disjoint source ownership.
#147 starts only after both implementation branches are merged or ready for
integration.

## Team assignment

Use model `gpt-6.1-sol` for every worker.

| Owner | Issues | Effort | Ownership |
| --- | --- | --- | --- |
| Engineer A | #144, then #148 | high | `docs/` inventory, canonical naming, deletion ledger, activity contract, fixtures |
| Engineer B | #145 | high | `finance-agent-core/**` and generated backend OpenAPI/fixtures |
| Engineer C | #146 | medium or high | `frontend/**`, excluding dependency manifests owned by #104 |
| Architect or integration owner | #147 | high | root verification scripts, Compose orchestration, cross-worker adapter handoff, final acceptance |

Maximum implementation fan-out is two feature engineers plus the integration
owner. Engineer A owns shared contract files. No other worker edits those files
concurrently.

## Start procedure

### 1. Ground the repository

The architect must first read `AGENTS.md`, this instruction,
`docs/backend-guideline.md`, `docs/frontend-guideline.md`, and the current
issues #143-#148. Run `how` over the backend runtime, LangGraph adapter, SSE,
frontend workflow consumer, and service clients. Use
`agent-implementation-extractor` for agent internals and
`agent-debug-review-playbook` for failures.

Record the baseline SHA, current test results, current Docker projects, and
known stale paths before assigning implementation work.

### 2. Create isolated worktrees

Start each worker from the same clean `main` SHA with separate branches and
directories:

```text
codex/refactor-contract-a
codex/refactor-backend-b
codex/refactor-frontend-c
codex/refactor-integration
```

No worker writes implementation code in `main`. Record each worktree path,
branch, base SHA, file ownership, and Compose project name.

### 3. Provision staging once, then automate it

The human operator has one setup responsibility: create or confirm the
dedicated staging user and add a disposable OpenRouter key. Use the normal
`/register` and `/settings/llm` flow. Do not ask the human to repeatedly test
the key during development.

The architect must create an untracked local secret bundle or approved OS
secret entry containing, without printing it:

```text
STAGING_EMAIL
STAGING_PASSWORD
STAGING_OPENROUTER_KEY
STAGING_PRIMARY_LABEL
STAGING_SECONDARY_LABEL
```

The current account can use the already healthy labels
`issue-97-staging-primary-replacement` and `issue-97-staging-secondary`. A new
account should use `full-refactor-staging-primary` and
`full-refactor-staging-secondary`.

`STAGING_BASE_URL` is not a human prerequisite and is not a secret. The
architect derives the host backend origin from that worktree's
`BACKEND_HOST_PORT`. The current shared staging happens to use
`http://127.0.0.1:8100`; another worktree may use `8000`, `8200`, or another
free port. An explicit `STAGING_BASE_URL` is allowed only as a local override
for a remote or separately managed endpoint. Never use the frontend port or
append `/api`.

The architect must create or assign an idempotent script under #147, for
example `scripts/refactor_staging_smoke.sh`, that:

- derives or validates the backend origin and checks `/health`;
- registers or logs in the staging user without leaking credentials;
- ensures the labelled key exists when the local raw key is available;
- tests the key and performs a bounded real provider request;
- records only masked metadata, request ID, latency, attempts, usage, and error code;
- is safe to rerun after a fresh database and never creates duplicate keys;
- never prints raw keys, passwords, cookies, authorization headers, prompts, or provider response bodies.

Engineers use fake providers and contract fixtures for ordinary development.
Only the architect/integration owner mutates the shared staging key pool during
failover tests. Other engineers may run bounded read/test requests, but must
not add, replace, or delete keys concurrently.

If the staging secret bundle is unavailable, continue all non-LLM work and mark
only the live provider gate `INCONCLUSIVE`. Do not ask for a raw key in chat or
put it into an issue.

### 4. Verify the Compose boundary

Read `.agents/skills/docker-development/SKILL.md` before any Compose action.
Each worktree must use:

- a unique explicit Compose project name;
- unique host ports and untracked local environment overrides;
- project-scoped volumes and networks;
- no fixed `container_name`;
- only the services needed for the current gate.

Validate with `docker compose -p <project> config --quiet`, then inspect
`docker compose -p <project> ps` and health endpoints. Serialize high-footprint
model builds. Do not run global `docker system prune --volumes`,
`docker volume prune`, or an unreviewed `docker image prune -a`.

## Pstack execution method

Every worker follows this loop:

1. **Ground:** use `how`, `why`, and the relevant project-specific skill.
2. **Sketch:** use `architect` before code. Define types, ports, module ownership, and error behavior. Compare two structurally different candidates for a major boundary.
3. **Implement in units:** use `principle-sequence-verifiable-units`; verify one coherent change before starting the next.
4. **Separate shared state:** use `principle-separate-before-serializing-shared-state`; give each worker a separate write target or serialize the real shared invariant.
5. **Review:** run `architecture-standard-enforcer`, `typescript-best-practices` for TypeScript, and the relevant concurrency/boundary/error guidance.
6. **Prove:** use `principle-prove-it-works` against the real artifact and local stack, not a self-report or compile-only proxy.

Use `figure-it-out` for the overall run and keep an auditable decision trail.
Every verdict is `VERIFIED`, `NOT VERIFIED`, or `INCONCLUSIVE`.

## Workstream acceptance gates

### #144: ownership and contract inventory

Engineer A inventories backend modules, agent entrypoints, REST routes, SSE
events, persistence tables, service clients, frontend features, and private
cross-slice imports. Every item receives one canonical name and one owner. The
deletion ledger marks each item delete, rename, or retain with a reason. This
issue changes documentation only and must pass the baseline architecture guard.

### #148: `workflow.activity` protocol

Engineer A deletes the design authority of `internal_progress` and defines the
typed activity contract with stable `activity_id`, `parent_activity_id`,
`thread_id`, `run_id`, `scope_path`, `kind`, lifecycle `status`, optional
measured `progress`, and `attempt`.

Fixtures must cover sequential nodes, parallel subgraphs, repeated invocations,
retries, interrupts, cancellation, failure, completion, duplicate delivery,
replay, and sequence gaps. Parallel activity uses a set; never infer a fake
aggregate percentage. Raw LangGraph namespaces and arbitrary state do not cross
the application boundary.

Do not upgrade LangGraph in this issue. Verify any newer typed streaming API in
a separate dependency gate before adopting it. The current implementation uses
the pinned runtime and `astream_events(..., version="v2")`.

### #145: backend architecture and runtime

Engineer B must:

- reduce `api/server.py` to lifespan, router assembly, dependency wiring, and boundary error mapping;
- move graph execution, run lifecycle, projection, persistence, replay, queue policy, and SSE framing behind owned typed ports;
- enforce authenticated ownership before thread lookup, replay, or subscription registration;
- delete `internal_progress` and all paths assigned to delete by #144;
- atomically persist the normalized event and cursor before publishing SSE;
- implement replay limits, `replay_gap`, subscribe/replay race handling, duplicate suppression, bounded queues, `subscriber_overloaded`, heartbeat, cancellation, and terminal events;
- keep LLM Provider, Model Inference, and Search behind typed clients and trusted internal principal context.

Acceptance requires fresh-database tests for ownership, storage failure,
ordering, replay, gaps, duplicates, slow consumers, cancellation, terminal
events, and generated OpenAPI alignment.

### #146: frontend architecture and workflow consumer

Engineer C must:

- make routes thin and give Auth, Workspace, LLM settings, Search settings, observability, and agent output explicit feature ownership;
- parse all external REST/SSE values from `unknown` into typed view models;
- hydrate snapshots before applying post-cursor deltas;
- deduplicate event IDs, detect sequence gaps, recover by replay/snapshot, reconnect with bounded backoff, and separate connection state from workflow state;
- render nested activity sets and optional progress without inferring one current node or a parallel aggregate percentage;
- delete obsolete endpoint/event branches, duplicate parsers, browser compatibility shapes, and unowned components.

Acceptance requires malformed payload rejection, cross-run/thread rejection,
duplicate/gap recovery, reconnect, cancellation, terminal, loading, empty,
stale, error, and degraded tests plus fresh-install lint, typecheck, and full
frontend tests.

### #147: integration and final cutover

The integration owner replaces process-local live fan-out with the shared
notification adapter handed off by #145. Start with PostgreSQL `LISTEN/NOTIFY`
and the durable event table; introduce another broker only if measured limits
require it. Sticky sessions are never correctness.

Run two API workers or replicas and prove live delivery, replay/live races,
disconnect recovery, worker exit recovery, cancellation, cleanup, bounded
queues, slow consumers, and terminal behavior. Run a final repository deletion
sweep for old routes, events, imports, generated contracts, aliases, obsolete
tables/columns, and stale architecture exceptions.

The final stack must pass fresh-database backend/frontend/service contract tests,
Compose health, architecture guard, TypeScript lint/typecheck, focused SSE
tests, and the real staging LLM smoke/failover gate. Production ingress, CDN,
and Agent Server validation remain deferred unless their deployment path exists.

## Worker report and merge policy

Each worker reports issue, branch, worktree, base/result SHA, file ownership,
accepted sketch, deviations, commands and exit codes, direct behavior evidence,
Docker project/health, verdict, residual gaps, and blockers. Reports contain no
secrets or unredacted provider data.

The architect independently inspects every diff and reruns the important checks
before merge. Merge in this order: Engineer A (#144/#148), Engineer B and C
(#145/#146), then integration (#147). Rebase each branch onto the accepted
contract handoff. Never close an issue from a self-report or `INCONCLUSIVE`
result.

## Final architect goal

Your goal is to complete the entire refactor represented by epic #143: merge the
accepted #144, #148, #145, #146, and #147 work into `main`, prove the fresh
backend/frontend/Docker stack and real staging LLM path work together, remove
all obsolete routes/events/imports/parsers/data paths and compatibility code,
and close the child issues only after recording `VERIFIED` evidence. The final
repository must be maintainable by the next engineer without relying on hidden
history, shared browser state, undocumented ports, or legacy behavior.
