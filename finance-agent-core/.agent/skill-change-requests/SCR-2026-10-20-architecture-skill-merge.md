# Skill Change Request

## 1) Context
- Request title: Merge duplicate agent architecture skills
- Date: 2026-10-20
- Requestor: User
- Related incident/issue/PR links: None

## 2) Problem Statement
- What happened? The project maintained both `agent-architecture-guard` and `architecture-standard-enforcer` with overlapping triggers, architecture checks, and output contracts.
- Why current skills/standards were insufficient: The duplicate entry points risked divergent instructions. The guard's reference copy was also older than the enforcer's canonical standard.
- Reproduction signals or evidence: Both skills cover agent layering, naming, runtime typing, async behavior, error/state contracts, logging, and migration hygiene; repository search found no other references to the guard skill.

## 3) Impact Scope
- Affected area(s): Agent architecture skill guidance.
- Affected modules/paths: `.agent/architecture-standard-enforcer/`, `.agent/skills/agent-architecture-guard/`, and the Codex user-level `architecture-standard-enforcer` mirror.
- Severity (P0/P1/P2/P3): P3
- User/business impact: One canonical skill entry point and a lower risk of inconsistent architecture reviews.

## 4) Proposed Skill/Standard Update
- Target category:
  - [x] Standard (`architecture-standard-enforcer`)
  - [ ] Planner (`architecture-modification-planner`)
  - [ ] Executor (`agent-refactor-executor`)
  - [ ] Debug/Review (`agent-debug-review-playbook`)
- Proposed update summary: Fold the guard's specific creation/change triggers, naming checks, typed runtime port guidance, and report requirements into the enforcer; remove the superseded guard skill.
- Exact file(s) to change: `.agent/architecture-standard-enforcer/SKILL.md`, `.agent/architecture-standard-enforcer/agents/openai.yaml`, `.agent/skills/agent-architecture-guard/**`, this SCR.
- Why this is generalizable (not case-specific): Both skills enforce the same cross-agent architecture standard and apply to the same source scope.

## 5) Risk and Compatibility
- Potential false positives/over-constraint risk: Existing source standard remains authoritative; workflow additions clarify how to apply it without adding new hard rules.
- Backward compatibility considerations: Explicit references to `$agent-architecture-guard` may need to be updated; none were found in the repository.
- Rollback plan: Restore the removed skill directory and revert the enforcer metadata/workflow update.

## 6) Validation Plan
- Required checks (lint/tests/contracts/log checks): Skill metadata/content validation if available; repository reference scan; diff whitespace check; project-to-Codex skill sync.
- Expected outcomes: The canonical skill contains the guard's useful guidance, the obsolete skill has no remaining references, and project/user-level enforcer copies match.
- Dogfooding scenario (real or representative task): Apply the consolidated workflow to review one representative agent module for ownership, naming, runtime boundaries, error/state/logging contracts, and migration hygiene.
- Results: `git diff --check` passed, repository search found no stale guard references, and `diff -ru` confirmed the project and Codex user-level enforcer copies match after `bash scripts/sync_skills.sh --reverse architecture-standard-enforcer`. `quick_validate.py` is not present in the project or Codex skills directory. The representative review surfaced a follow-up candidate: `FundamentalOrchestrator` carries several `*_fn` callables across the orchestrator/use-case boundary (`src/agents/fundamental/application/workflow_orchestrator/orchestrator.py:50` and `:176`); code remediation is outside this skill-merge scope.

## 7) Decision and Ownership
- Skill owner: `architecture-standard-enforcer`
- Required approver(s): User
- Decision:
  - [x] Approved
  - [ ] Needs revision
  - [ ] Rejected
- Decision notes: Implemented at the user's explicit request.

## 8) Follow-up
- Implementation PR: Not created in this task.
- Post-merge verification date: 2026-10-20
- Additional actions: Assess the callable bundle candidate in a separate architecture review. The later project-local migration is recorded in `SCR-2026-10-20-project-architecture-skill-governance.md`; future enforcer updates are maintained in repository-root `.agents/skills/` and are not synced to the user skill directory.
