---
name: skill-governance-maintainer
description: Maintain and govern skill quality updates using canonical Skill Change Request (SCR) and Skill PR templates. Use when proposing, reviewing, or implementing changes to skills/standards/playbooks, and when deciding whether updates belong in standard, planner, executor, or debug-review skills.
---

# Skill Governance Maintainer

## Purpose

Govern skill evolution with a repeatable process.
Use canonical templates to keep updates auditable, concise, and non-duplicative.

## Canonical Governance References

In `finance-agent-core`, always use these canonical files:
- `.agent/references/skill-change-request-template.md`
- `.agent/references/skill-pr-template.md`

Do not duplicate these templates into individual skills unless portability is explicitly required.

## Workflow

1. Intake the change signal.
- Gather trigger evidence: incident, repeated review finding, regression, or repeated refactor friction.
- Confirm this is a reusable pattern, not a one-off case.

2. Classify ownership.
- Route updates to one owner class:
  - `architecture-standard-enforcer` for cross-agent hard rules.
  - `architecture-modification-planner` for planning structure and sequencing guidance.
  - `agent-refactor-executor` for implementation slice policy and execution gates.
  - `agent-debug-review-playbook` for debugging/review methodology and findings quality.

3. Create SCR.
- Fill `.agent/references/skill-change-request-template.md` completely.
- Include scope, severity, generalization rationale, risk, compatibility, and validation plan.

4. Implement skill updates.
- Apply minimal changes to the chosen skill.
- Keep SKILL body concise; place detailed material in references only when needed.
- Avoid introducing duplicate policy text across multiple skills.

5. Prepare PR using canonical template.
- Fill `.agent/references/skill-pr-template.md` in PR description.
- Link SCR, changed files, validation commands/results, and rollback notes.

6. Validate and merge.
- Run `quick_validate.py` for every changed skill.
- Ensure at least one representative dogfooding run is documented.

7. Post-merge governance check.
- Confirm no stale references or conflicting duplicate rules remain.
- Record follow-up signals for next governance triage.

## Output Contract

For each governance run, output:
- `Classification`: target skill owner and reason.
- `SCR Checklist`: completed vs missing fields.
- `Change Plan`: exact skill files to modify.
- `Validation Plan`: commands and expected pass criteria.
- `Merge Readiness`: blockers and next action.

## Guardrails

- Keep canonical templates in `.agent/references/` as single source of truth.
- Reject case-specific rules that do not generalize.
- Prefer edits over new skills unless capability boundaries truly differ.
- Keep governance artifacts implementation-oriented and concise.
