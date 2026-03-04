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

## Workflow

1. Normalize scope and goals.
- Split requirements into objective, constraints, and non-goals.
- Resolve ambiguities by stating assumptions explicitly.

2. Build impact map.
- Identify directly changed files and indirectly impacted dependencies.
- Map boundary crossings (`domain/application/interface/infrastructure`).

3. Design phased execution plan.
- Sequence changes into low-risk phases with clear entry/exit criteria.
- Prefer atomic migration per slice when feasible.

4. Define risk and rollback strategy.
- List functional, runtime, and migration risks.
- Define fallback or rollback checkpoints per phase.

5. Define validation strategy.
- Specify lint/tests/contracts/log checks needed per phase.
- Specify what cannot be validated yet and why.

6. Produce final planning document.
- Keep language precise and implementation-oriented.
- Do not output source code.

## Output Contract

Use this structure:
- `Requirement Breakdown`
- `Technical Objectives and Strategy`
- `Involved Files`
- `Detailed Per-File Plan`
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
