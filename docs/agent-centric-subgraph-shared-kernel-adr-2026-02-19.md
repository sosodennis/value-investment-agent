# ADR: Agent-Centric Subgraph Ownership and Shared Kernel Consolidation
Date: 2026-02-19
Status: Accepted
Scope: `finance-agent-core`

## 1. Context

Current architecture already uses per-agent layered packages (`domain/application/data/interface`) with workflow-level graph composition.

Recent refactors completed these goals:
1. Workflow nodes are mostly thin routers.
2. Boundary mapping has moved into interface/application boundaries.
3. Typed boundary policies and incident logging schema are established.

Remaining architecture friction:
1. Subgraph assembly is still centralized under `src/workflow/nodes/*/graph.py`, so ownership is split between workflow and agent packages.
2. Similar handoff/result contracts and route translation patterns are repeated across agents.
3. Shared boundary logging policy exists, but reusable contract/helper ownership is not fully centralized.

## 2. Decision

We adopt the following architecture decisions for the next phase:

1. Agent-centric subgraph ownership.
   - Each agent package is responsible for its own subgraph builder entrypoint.
   - Workflow layer composes subgraphs and global transitions only.
2. Shared kernel consolidation for cross-agent reusable runtime contracts.
   - Shared kernel is the single source of truth for reusable handoff/result contract types and shared boundary logging helper contracts.
   - Agent-specific semantics stay inside each agent package.
3. Keep current deployment topology.
   - No workspace package split in this phase.
   - No independent per-agent deployment in this phase.

## 3. Rationale

1. Improves ownership clarity:
   - "Agent behavior + agent subgraph" changes in one place.
2. Reduces duplication risk:
   - Common runner/handoff/result contracts become shared kernel SSOT.
3. Preserves existing governance:
   - Keeps Simple Triad, strict boundary typing, and fail-fast rules intact.
4. Minimizes migration risk:
   - Refactor scope stays in-process within current monorepo/package structure.

## 4. Non-Goals

1. No workspace-based package split.
2. No deployment decomposition to per-agent runtime units.
3. No compatibility layer for legacy boundary shapes.

## 5. Target Ownership Model

1. Agent package (`src/agents/<agent>/**`):
   - owns subgraph builder and internal graph/node assembly for that agent
   - owns domain/application/data/interface semantics for that agent
2. Shared kernel (`src/shared/kernel/**`):
   - owns reusable cross-agent runtime contracts and boundary logging primitives
3. Workflow (`src/workflow/**`):
   - owns top-level graph composition and cross-agent/global transitions only

## 6. Migration Policy

1. Migrate incrementally agent by agent.
2. Keep workflow node behavior parity during migration.
3. Remove dead wrappers/imports immediately after each migration step.
4. Each PR must include:
   - touched boundary tests
   - doc updates when ownership/contracts change

## 7. Risk and Mitigation

1. Risk: temporary duplication during migration.
   - Mitigation: define canonical entrypoint names first, then delete obsolete paths in the same PR when safe.
2. Risk: contract drift between agents.
   - Mitigation: shared kernel contract types + boundary regression tests.
3. Risk: accidental logic leakage back to workflow.
   - Mitigation: keep workflow "composition-only" rule in code review checklist.

## 8. Acceptance Criteria

1. Agent subgraph assembly is package-owned for all target agents.
2. Shared kernel provides canonical reusable handoff/result contract types.
3. Boundary logging contract usage is consistent in incident-prone paths.
4. Workflow layer does not regain business mapping/serialization logic.
