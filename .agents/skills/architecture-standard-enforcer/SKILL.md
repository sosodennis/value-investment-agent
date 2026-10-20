---
name: architecture-standard-enforcer
description: Enforce the project's vertical-slice agent architecture across public entrypoints, agent workflows, capabilities, shared contracts, and the root graph. Use when creating or changing agent code, reviewing architecture, or validating a module refactor.
---

# Architecture Standard Enforcer

Use this as the single compliance entrypoint for agent architecture work.

## Required Reference

Read `references/cross-agent-architecture-standard.md` before analysis. It is the canonical source for package ownership, import direction, capability boundaries, and graph contracts.

## Workflow

1. Scope changed agent modules and directly affected graph or shared-contract boundaries.
2. Map observed ownership across `entrypoint.py`, `workflow/`, `application/`, `domain/`, optional `capabilities/`, `infrastructure/`, optional `interface/`, root workflow, and shared contracts. Separate current structure from target structure.
3. Check dependency direction, root graph imports, cross-agent imports, capability facades, and capability cycles. Treat existing `subdomains/`, `src/workflow/nodes/<agent>/`, and `application/subgraph.py` as migration-era paths; new capability code belongs under `capabilities/`.
   - A public entrypoint may use only its own `application.wiring` factory for default graph construction and should retain runner injection for fake-adapter tests.
4. Review relevant runtime contracts: typed ports, state normalization, async I/O and compute, persistence semantics, degraded outcomes, and structured diagnostics.
5. For import-boundary changes, run `python3 scripts/architecture_guard.py` from the repository root. Use `finance-agent-core/src/agents/ARCHITECTURE_MODULE_ACTIONS.md` to locate documented legacy edges. An allowlisted edge is tracked migration debt, not a recommended dependency.
6. For graph changes, run `uv run pytest tests/agents/*/test_subgraph_entrypoint.py -q` from `finance-agent-core`; confirm fake adapters are reached and input/output schemas remain defined. If a migrated agent has its own focused test, run that test directly as well.
7. Report severity-ranked findings with file/line, impact, the smallest remediation, validation, and remaining coverage gaps. Say explicitly when no findings remain.

## Review Focus

- Keep each agent's state, nodes, and subgraph within that agent's `workflow/` package.
- Keep use-case coordination in application and deterministic rules in domain. Infrastructure owns external adapters; composition belongs at a boundary.
- Use stable public entrypoints and capability facades instead of imports into another slice's private modules.
- Add a capability only when its ownership and public contract reduce coupling. Do not create empty layers, split by LOC alone, or preserve compatibility aliases after callers migrate.
- Apply naming, runtime, state, error, and logging details from the canonical reference; do not restate or extend its rules here.

## Guardrails

- Do not infer that the target architecture is already implemented. Ground findings in the current source tree.
- Do not create new architecture exceptions as a shortcut. Existing exceptions must map to a current report action and are removed when their edge is resolved.
- Prefer focused remediation over broad restructuring unless the requested scope is a full module migration.
