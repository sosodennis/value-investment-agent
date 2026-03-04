---
name: skill-governance-maintainer
description: Maintain and govern skill quality updates using canonical Skill Change Request (SCR) and Skill PR templates, plus controlled skill sync between project and codex directories. Use when proposing, reviewing, implementing, deduplicating, or pruning skill updates, and when deciding whether to edit existing skills or create a new one.
---

# Skill Governance Maintainer

## Purpose

Govern skill evolution with a repeatable process.
Use canonical templates to keep updates auditable, concise, and non-duplicative.
Prefer updating existing skills over adding new skills.

## Canonical Governance References

In `finance-agent-core`, always use these canonical files:
- `.agent/references/skill-change-request-template.md`
- `.agent/references/skill-pr-template.md`

Do not duplicate these templates into individual skills unless portability is explicitly required.

## Canonical Source and Sync

Use one canonical editing source per team workflow:
- Recommended canonical source: `~/.codex/skills`
- Project mirror: `finance-agent-core/.agent`

When both locations are used, synchronize explicitly with:
- `finance-agent-core/scripts/sync_skills.sh`

Default sync (codex -> project):
- `bash finance-agent-core/scripts/sync_skills.sh`

Preview before sync:
- `bash finance-agent-core/scripts/sync_skills.sh --dry-run`

Reverse sync (project -> codex):
- `bash finance-agent-core/scripts/sync_skills.sh --reverse`

Never assume automatic sync between the two locations.

## Update-First Decision Gate (Hard Rule)

Before creating a new skill, run this gate in order:

1. `Can existing skills absorb the change with <= 20 lines in SKILL.md or one new reference file?`
- If yes, update existing skill. Do not create new skill.

2. `Is the capability boundary genuinely different (new trigger, different workflow owner, different output contract)?`
- If no, update existing skill.

3. `Will adding a new skill reduce duplication instead of creating it?`
- If no, update existing skill.

Create a new skill only if all three checks pass.

## Anti-Bloat Rules

- Keep `SKILL.md` concise and procedural; move detailed content to `references/` only when needed.
- Do not copy the same policy text into multiple skills.
- If two skills overlap > 30% in workflow, merge or split responsibilities explicitly.
- Remove stale or superseded instructions immediately after migration.
- Keep one canonical location for governance templates and reference from skills.

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

4. Decide update vs create.
- Apply the `Update-First Decision Gate`.
- If gate fails, update existing skill; do not add a new one.
- If gate passes, document why a new skill is required in SCR.

5. Implement skill updates.
- Apply minimal changes to the chosen skill.
- Keep SKILL body concise; place detailed material in references only when needed.
- Avoid introducing duplicate policy text across multiple skills.

6. Prepare PR using canonical template.
- Fill `.agent/references/skill-pr-template.md` in PR description.
- Link SCR, changed files, validation commands/results, and rollback notes.

7. Validate and merge.
- Run `quick_validate.py` for every changed skill.
- Ensure at least one representative dogfooding run is documented.

8. Sync and post-merge governance check.
- Run skill sync to keep codex/project copies aligned.
- Confirm no stale references or conflicting duplicate rules remain.
- Record follow-up signals for next governance triage.

## Output Contract

For each governance run, output:
- `Classification`: target skill owner and reason.
- `Update-vs-Create Decision`: gate result and rationale.
- `SCR Checklist`: completed vs missing fields.
- `Change Plan`: exact skill files to modify.
- `Validation Plan`: commands and expected pass criteria.
- `Sync Plan`: direction and command to keep mirrors aligned.
- `Merge Readiness`: blockers and next action.

## Guardrails

- Keep canonical templates in `.agent/references/` as single source of truth.
- Reject case-specific rules that do not generalize.
- Prefer edits over new skills unless capability boundaries truly differ.
- Do not let codex/project skill copies drift; sync after governance updates.
- Keep governance artifacts implementation-oriented and concise.
