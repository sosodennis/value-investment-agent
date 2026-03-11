---
name: agent-refactor-executor
description: Execute approved refactor plans in controlled medium/small slices with strict validation and compliance gates. Use when implementation must follow an existing plan, keep migration safe, preserve delivery speed, and produce auditable per-slice progress with tests, lint checks, and architecture-standard compliance results.
---

# Agent Refactor Executor

## Purpose

Implement refactors from an approved plan without drifting scope.
Balance safety and speed by enforcing medium/small slices with explicit validation gates.

## Required Inputs

Collect these before execution:
- Approved refactor plan (recommended source: `$architecture-modification-planner`).
- Scope boundaries and non-goals.
- Required validation gates (lint, tests, contract checks, logging checks).
- Rollback expectations and compatibility constraints.
- Ownership decisions for any moved contracts/ports and old → new path mapping.
- Legacy removal constraints (no compatibility shims unless explicitly approved).

## Slice Policy (Hard Rules)

1. Only `small` and `medium` slices are allowed by default.
2. Default to `medium` slices to preserve throughput.
3. Use `small` slices for high-risk changes:
- Cross-layer boundary rewiring.
- Contract relocation across layers or subdomains.
- Async/runtime boundary changes.
- State/error contract changes.
- Migration/removal of compatibility paths.
4. Disallow `micro` slices with no independent verification value.
5. If a slice cannot be validated independently, merge it with adjacent work into one verifiable slice.
6. `large` slices require explicit exception approval with risk note, rollback point, and validation plan.

## Execution Workflow

1. Initialize execution context.
- Restate objective, in-scope files, out-of-scope files, and acceptance gates.
- Confirm ownership decisions for moved contracts and old → new path mapping.

2. Segment plan into executable slices.
- Tag each slice as `small` or `medium`.
- Define entry condition, expected output, and validation gate per slice.

3. Execute one slice at a time.
- Apply only changes required for the current slice.
- Avoid opportunistic edits outside current scope.

4. Validate immediately after each slice.
- Run required checks for that slice.
- Record pass/fail with concise evidence.
- Run legacy import/path sweep when migration is involved (for example `rg` old paths).

5. Run compliance gate.
- Invoke `$architecture-standard-enforcer` on changed paths.
- Block progression if hard-rule violations remain.

6. Handle failures deterministically.
- If validation or compliance fails, switch to `$agent-debug-review-playbook`.
- Apply smallest reliable remediation and re-run gates.

7. Close and hand off.
- Summarize completed slices, residual risks, and next pending slice.
- Confirm empty layer directories were removed after migration.

## Output Contract (Per Iteration)

- `Executed Slice`: id, size (`small|medium`), objective.
- `Files Changed`: explicit list.
- `Validation Results`: checks run and status.
- `Compliance Results`: pass/fail and blocking violations.
- `Risk/Rollback Notes`: current risk and fallback point.
- `Next Slice`: next planned slice or stop condition.

## References

- `references/execution-checklist.md`
- `references/handoff-template.md`
- `references/rollback-playbook.md`

## Guardrails

- Do not rewrite the approved plan unless a blocker is proven.
- Do not batch multiple high-risk changes in one slice.
- Do not continue if a hard compliance violation is unresolved.
- Keep change sets minimal, reversible, and test-backed.
- Do not leave compatibility shims or re-export modules unless explicitly approved.
