# One-Click Audit + Refactor Planning Prompt Template

Use this prompt when you want a single run to perform architecture compliance audit first, then produce a no-code refactor plan.

## Template

```text
Use $architecture-standard-enforcer first, then $architecture-modification-planner.

Scope:
- Target path(s): <PATHS>
- Optional boundary modules: <BOUNDARY_PATHS>
- Optional commit/PR context: <CONTEXT>

Task:
1) Audit the scoped code for compliance against canonical cross-agent architecture standards.
2) If violations exist, produce a phased, no-code refactor plan.
3) If no violations exist, state that explicitly and list residual risks/test gaps.

Output requirements:
- Findings: severity-ordered, with file path, line number, violated rule section, and impact.
- Assumptions/Open Questions: only blockers.
- Refactor Plan: file-by-file change plan, sequencing, dependencies, and risk controls.
- Validation: exact checks to run (lint/tests/contracts/logging) and expected pass criteria.

Constraints:
- Do not generate code.
- Keep recommendations minimal, maintainable, and migration-safe.
- Prefer atomic migration per slice whenever feasible.
```

## Example (finance-agent-core)

```text
Use $architecture-standard-enforcer first, then $architecture-modification-planner.

Scope:
- Target path(s): finance-agent-core/src/agents
- Optional boundary modules: finance-agent-core/src/interface, finance-agent-core/src/infrastructure
- Optional commit/PR context: refactor draft for strategist and scout nodes

Task:
1) Audit the scoped code for compliance against canonical cross-agent architecture standards.
2) If violations exist, produce a phased, no-code refactor plan.
3) If no violations exist, state that explicitly and list residual risks/test gaps.

Output requirements:
- Findings: severity-ordered, with file path, line number, violated rule section, and impact.
- Assumptions/Open Questions: only blockers.
- Refactor Plan: file-by-file change plan, sequencing, dependencies, and risk controls.
- Validation: exact checks to run (lint/tests/contracts/logging) and expected pass criteria.

Constraints:
- Do not generate code.
- Keep recommendations minimal, maintainable, and migration-safe.
- Prefer atomic migration per slice whenever feasible.
```
