# Agent Architecture Standard

Scope: `finance-agent-core/src/agents/*`, `src/workflow/*`, and shared contracts.
Status: Active; existing violations are tracked in the module action report.

This document is the canonical architecture policy for agent work. The current source tree is still migrating; describe code as observed and distinguish it from this target.

## 1. Ownership and Package Shape

Each agent is a vertical slice and owns its public entrypoint, graph contract, use cases, domain rules, and adapters.

```text
src/agents/<agent>/
  entrypoint.py                 # public inputs/outputs and graph entry
  workflow/                     # state, nodes, graph and routing
  application/                  # use-case coordination and ports
  domain/                       # deterministic business rules
  capabilities/<capability>/    # optional cohesive, independently bounded capability
  infrastructure/               # external data and persistence adapters
```

- `workflow/` is part of every agent slice. It owns the agent state, nodes, and subgraph. A capability may own another workflow only when it has an independently useful state machine.
- Add layers only where they clarify ownership. A thin agent does not need empty `domain/` or `infrastructure/` directories.
- Prefer `capabilities/` for new capability packages. Existing `subdomains/` paths are migration-era paths and remain visible in the action report; do not create new ones.
- A capability exposes stable imports through its package facade or a direct `api`, `contracts`, or `public` module. Other capabilities must not import its implementation files.
- `src/workflow/` is the cross-agent composition root. It assembles agent entrypoints and shared contracts; it does not own an agent's state or private nodes.
- Shared contracts and platform code must not import agent packages. Move a genuinely cross-agent contract to `src/shared/` rather than depending on one agent's private implementation.

## 2. Dependency Direction

Dependencies point toward policy and stable contracts:

| Source | May depend on | Must not depend on |
| --- | --- | --- |
| `domain` | same domain, stable shared/domain contracts | application, interface, workflow, entrypoint, composition, I/O adapters |
| `application` | domain, declared ports/contracts, capability facades, shared contracts | concrete infrastructure, workflow, entrypoint, composition |
| `interface` | domain and shared contracts | application, infrastructure, workflow, entrypoint, composition |
| `workflow` | agent application/domain contracts, capability facades, shared contracts, same workflow | concrete infrastructure, root workflow internals, entrypoint, composition |
| `infrastructure` | application ports, domain contracts, shared contracts | workflow, entrypoint, composition |
| `entrypoint` | its agent's public graph and boundary contracts; its own `application.wiring` factory for default graph construction | concrete infrastructure, another agent's private modules or composition wiring, root workflow internals |
| composition/wiring | application ports, workflow builders, domain contracts, and infrastructure adapters | root workflow internals; policy code importing the composition module |

Additional hard rules:

1. The root workflow imports an agent's `entrypoint.py`, never its private state, node, application, or infrastructure modules.
2. Cross-agent imports target the other agent's public entrypoint or a shared contract. Agent internals do not reach into another agent's package.
3. Cross-capability imports target the capability facade. Capability dependency cycles are forbidden, including cycles that pass through public facades.
4. `domain` contains deterministic policy and models; it does not call networks, storage, frameworks, or LLMs.
5. `application` coordinates use cases through typed ports. Composition code constructs adapters at the boundary; use cases do not import concrete adapters.
6. `interface`, when present, owns external schemas, serialization, mapping, and prompt specifications. It does not own application orchestration, domain policy, or I/O.
7. `infrastructure` owns provider/client/repository adapters. Repository adapters perform persistence access and do not absorb domain aggregation or workflow routing.
8. An agent entrypoint may use only its own `application.wiring` factory to construct the default graph or runner when none is injected. Keep runner injection available so tests can provide fake adapters. Application-to-entrypoint imports remain forbidden.

The CI check is `python3 scripts/architecture_guard.py`. Its exception file lists exact legacy module edges and an action ID from `src/agents/ARCHITECTURE_MODULE_ACTIONS.md`. Exceptions are temporary migration records: new edges fail CI, removed edges make the old exception fail as stale, and each fix removes its exception.

## 3. Graph Contract

- Keep graph state, node adapters, and subgraph construction inside the owning agent's `workflow/` package.
- The public entrypoint presents stable input/output schemas and delegates graph execution to that workflow. It obtains the default graph or runner through its own `application.wiring` factory when no runner is supplied; callers can inject a runner for tests.
- Test every agent graph with fake adapters: the graph builds, input/output schemas exist, and a minimal invocation reaches the fakes without live providers.
- Test migrated agents through their public `entrypoint.py` with fake adapters. Legacy `application/subgraph.py` builders and root workflow node tests may remain temporarily while callers migrate, but they are compatibility coverage rather than the target graph contract.

## 4. Implementation Standards

- Prefer clear ownership and typed contracts. Do not split modules only to reduce line count or create a layer without an owner responsibility.
- Use role-specific names: `Provider` for one upstream source, `Client` for transport, `Repository` for persistence, `Service` for coordination, `Factory` for assembly, `Mapper` for shape conversion, `Policy` for deterministic rules, and `Port` for protocols only.
- Keep raw `object` values at decode or LangGraph state boundaries; normalize them before they enter application/domain contracts.
- Make partial workflow state reads tolerant. Keep error updates machine-readable and distinguish missing artifacts from valid empty payloads.
- In async workflows, use async APIs or offload blocking I/O and heavy computation. Reuse long-lived clients on hot paths and bound heavy-compute concurrency.
- Return typed degraded outcomes instead of bare `None` when callers need a failure reason. Emit structured completion and degradation logs with stable event names and bounded diagnostic fields.
- Migrate callers and remove obsolete paths within the same slice when practical. A narrowly scoped compatibility shim may remain only while an explicitly owned caller is scheduled in another slice; keep it tested and remove it with that caller migration.

## 5. Review Checklist

1. Does every changed module have one clear owner and point dependencies inward?
2. Does the root workflow depend only on public agent entrypoints and shared contracts?
3. Do capability imports use facades, and is the capability graph acyclic?
4. Can each changed agent graph build and run with fake adapters?
5. Are application contracts typed, infrastructure calls kept at boundaries, and domain rules deterministic?
6. Are partial state, degraded results, persistence misses, and async work handled explicitly?
7. Were resolved edges removed from the exception file and the module action report refreshed?

Update this standard only when an approved architecture decision changes a reusable rule. Keep implementation evidence and migration findings in the action report, not in this policy.
