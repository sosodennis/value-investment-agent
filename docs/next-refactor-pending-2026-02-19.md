# Next Refactor Pending
Date: 2026-02-19
Scope: `finance-agent-core/src/agents/*`, `finance-agent-core/src/shared/kernel/**`, `finance-agent-core/src/workflow/**`
Policy Baseline: Agent-centric subgraph ownership + shared kernel normalization + strict typed boundary.

This is the single source of truth for open refactor work for the 2026-02-19 phase.

## Status Update (2026-02-19)

1. Previous backlog (`2026-02-16`) is complete; this file starts the next phase.
2. Refactor focus is narrowed to:
   - subgraph ownership moving toward agent packages
   - shared kernel contracts/utilities consolidation
3. Explicitly out of scope in this phase:
   - workspace packaging / multi-package split
4. P0-1 progress:
   - Shared workflow node result contracts added at `src/shared/kernel/workflow_contracts.py`.
   - Agent orchestrators now use shared aliases for node result contracts (single-target / fan-out).
5. P0-2 progress:
   - Shared boundary contract kinds and payload types added at `src/shared/kernel/boundary_contracts.py`.
   - Boundary logger now uses typed boundary payload contracts (`BoundaryEventPayload`, `BoundaryReplayDiagnostics`).
6. P0-3 progress:
   - Added regression tests for shared workflow/boundary contracts:
     - `finance-agent-core/tests/test_kernel_workflow_contracts.py`
7. P1-3 progress:
   - Shared workflow routing helper added: `src/shared/kernel/workflow_routing.py`.
   - Shared workflow command adapter added: `src/workflow/command_adapter.py`.
   - Workflow node command assembly paths now use shared adapter/helper to remove duplicated END mapping logic.
8. P1-1 progress:
   - Agent-owned subgraph entrypoints added:
     - `src/agents/intent/subgraph.py`
     - `src/agents/fundamental/subgraph.py`
     - `src/agents/news/subgraph.py`
     - `src/agents/technical/subgraph.py`
     - `src/agents/debate/subgraph.py`
   - Parent workflow graph now imports subgraph builders from agent packages.
9. P2-1 progress:
   - Removed transitional compatibility wrappers under `src/workflow/nodes/*/graph.py`.
   - Tests and imports now reference agent-owned subgraph entrypoints directly.
10. P2-2 progress:
   - Updated agent-owned subgraph builders to current LangGraph API:
     - `StateGraph(..., input_schema=..., output_schema=...)`
     - `add_node(..., retry_policy=RetryPolicy(...))`
   - Removed LangGraph v0.5 deprecation warnings from subgraph compile path.

## P0 (Must Do First)

1. Define shared workflow handoff/result contracts in shared kernel.
   - Standardize runner result shape used by workflow nodes (`goto`, `update`, boundary error metadata).
   - Remove per-agent ad-hoc result typing where it duplicates the same contract.
2. Normalize shared boundary logging usage.
   - Use one shared boundary logging helper path and one schema for boundary incidents.
   - Ensure key boundaries emit the required keys consistently (`node`, `artifact_id`, `contract_kind`, `error_code`, `replay`).
3. Add boundary-focused regression tests for shared contracts/helpers.
   - Validate contract parse/serialize behavior.
   - Validate logging payload schema consistency.

## P1 (Agent-Centric Subgraph Ownership)

1. Move each agent subgraph assembly responsibility into the corresponding agent package.
   - Target ownership: agent package exports canonical subgraph builder entrypoint.
   - Workflow layer should only compose agent subgraphs and define global transitions.
2. Keep workflow nodes thin and orchestration-only after migration.
   - No business mapping logic or boundary serialization logic in workflow nodes.
3. Reduce duplicate route/command translation helpers.
   - Prefer shared helper(s) where behavior is identical across agent nodes.

## P2 (Stability / Cleanup)

1. Remove dead transitional wrappers/import surfaces introduced during migration.
2. Add/adjust architecture docs and checklists to match final ownership.
3. Ensure quality gates pass on touched files and boundary suites.

## Remaining Pending

1. P0 items are in progress (not complete).
2. P1 items are in progress.
3. P2 items are open.

## Definition of Done

1. Every agent has a canonical, package-owned subgraph builder entrypoint.
2. `src/workflow/**` is limited to global composition and orchestration wiring.
3. Shared kernel owns reusable handoff/result contracts and boundary logging helpers.
4. No duplicated boundary contract logic across agents for equivalent concerns.
5. New changes pass lint/tests and boundary regression checks in one PR.
