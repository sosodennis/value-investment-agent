---
name: architecture-modification-planner
description: Produce implementation-ready architecture modification plans without writing code. Use when converting requirements and review findings into phased refactor plans, impacted-file maps, dependency and risk analysis, validation strategy, and clear execution sequencing for multi-file or cross-layer changes.
---

# Architecture Modification Planner

## Purpose

Turn requirements and review findings into a deterministic, no-code implementation plan.
Keep scope explicit, risks visible, and sequencing executable.

## Inputs

Collect these inputs before planning:
- User requirement and success criteria.
- Current constraints (time, compatibility, rollout expectations).
- Findings from architecture review (recommended: `$architecture-standard-enforcer`).
- Relevant code context and affected module boundaries.
- Ownership decisions needed for moved contracts/ports (domain vs application vs interface).

## Workflow

1. Normalize scope and goals.
- Split requirements into objective, constraints, and non-goals.
- Resolve ambiguities by stating assumptions explicitly.

2. Build impact map.
- Identify directly changed files and indirectly impacted dependencies.
- Map boundary crossings (`domain/application/interface/infrastructure`).
- Flag potential subdomain split candidates (stable capability boundary, unique deps, or pipeline stages).

3. Design phased execution plan.
- Sequence changes into low-risk phases with clear entry/exit criteria.
- Prefer atomic migration per slice when feasible.
- Include legacy removal steps in the same slice as call-site migration.

4. Define risk and rollback strategy.
- List functional, runtime, and migration risks.
- Define fallback or rollback checkpoints per phase.

5. Define validation strategy.
- Specify lint/tests/contracts/log checks needed per phase.
- Specify what cannot be validated yet and why.
- Include import hygiene and legacy-path sweep checks when paths move.

6. Produce final planning document.
- Keep language precise and implementation-oriented.
- Do not output source code.
- Record ownership decisions and rationale for any contract relocation.

## Output Contract

Use this structure:
- `Requirement Breakdown`
- `Technical Objectives and Strategy`
- `Involved Files`
- `Detailed Per-File Plan`
- `Old → New Mapping`
- `Risk/Dependency Assessment`
- `Validation and Rollout Gates`
- `Assumptions/Open Questions`

## Reference Templates

- One-click review + planning prompt:
  - `references/one-click-audit-plan-prompt-template.md`

## Guardrails

- Do not generate code.
- Tie every proposed change to a requirement or finding.
- Prefer minimal and maintainable sequencing over large-batch rewrites.
- Do not propose compatibility shims unless explicitly approved as a constraint.

## Ownership Decision Rubric (Boundary Placement)
- `domain`: deterministic business concepts/policies; no I/O.
- `application`: use-case ports and orchestration boundaries.
- `interface`: boundary DTOs/serializers/projections and prompt specs.
- `infrastructure`: adapters, providers, repositories, wiring only.

## Subdomain Split Criteria (When to Split)
- **Capability boundary**: a coherent capability has a stable API and can evolve independently.
- **Dependency boundary**: distinct external dependencies or data sources justify a separate subdomain.
- **Pipeline boundary**: multi-stage pipelines (fetch/extract/map/score/postprocess) benefit from stage grouping or subdomain split.
- **Ownership boundary**: different teams or lifecycles need isolated changes and tests.
- **Cohesion signal**: 4+ tightly-coupled owner modules in one area that change together repeatedly.
- **Do not split** if it only reduces LOC or increases indirection without clear boundary value.
