# Skill Change Request

## 1) Context
- Request title: Make finance-agent architecture skills project-local and maintain them after architecture changes
- Date: 2026-10-20
- Requestor: User
- Related incident/issue/PR links: None

## 2) Problem Statement
- What happened? Pstack was installed at the repository root while the three finance-agent architecture skills lived under `finance-agent-core/.agent` and also had same-name copies in the Codex user skill directory.
- Why current skills/standards were insufficient: The project skills were not in Codex's repository skill discovery path, and global duplicates could surface outside this project. No workflow required reconciling their guidance after architecture changes.
- Reproduction signals or evidence: Codex scans repository `.agents/skills`; it does not treat this repository's `.agent` folder as that skill root. The project copies had identical user-level copies.

## 3) Impact Scope
- Affected area(s): Project skill routing and architecture guidance maintenance.
- Affected modules/paths: Repository-root `AGENTS.md`, `.agents/skills/`, `finance-agent-core/.agent/skill-governance-maintainer/`, and this SCR.
- Severity (P0/P1/P2/P3): P3
- User/business impact: Project-specific guidance becomes discoverable only in this repository and stays aligned with architecture decisions.

## 4) Proposed Skill/Standard Update
- Target category:
  - [ ] Standard (`architecture-standard-enforcer`)
  - [ ] Planner (`architecture-modification-planner`)
  - [ ] Executor (`agent-refactor-executor`)
  - [ ] Debug/Review (`agent-debug-review-playbook`)
  - [x] Skill governance/maintenance (`architecture-skill-maintainer`)
- Proposed update summary: Move the implementation extractor, debug review playbook, and architecture enforcer to the repository-root `.agents/skills/`; add `architecture-skill-maintainer`; route pstack and the project skills through `AGENTS.md`; keep multi-step task tracking project-local; clarify the project-local source exception in the governance skill.
- Exact file(s) to change: `AGENTS.md`, `.agents/skills/{agent-implementation-extractor,agent-debug-review-playbook,architecture-standard-enforcer,architecture-skill-maintainer}/**`, `finance-agent-core/.agent/skill-governance-maintainer/{SKILL.md,agents/openai.yaml}`, `finance-agent-core/.agent/references/{skill-change-request-template.md,skill-pr-template.md}`, `~/.codex/skills/skill-governance-maintainer/{SKILL.md,agents/openai.yaml}`, this SCR.
- Why this is generalizable (not case-specific): Project-local agent architecture guidance must be discoverable in the repository and updated when its underlying architecture contracts change.

## 5) Risk and Compatibility
- Potential false positives/over-constraint risk: A new maintenance pass after every ordinary code edit would add noise; the trigger is limited to material topology, state/workflow, runtime-boundary, or ownership changes.
- Backward compatibility considerations: The three global copies are moved to Trash to prevent same-name global entries; the project-local task-tracking policy does not affect other projects.
- Rollback plan: Restore the three archived skill copies from `/Users/denniswong/.Trash/finance-agent-core-architecture-skills-2026-10-20/`, move project skills back to `finance-agent-core/.agent`, and revert routing/governance edits.

## 6) Validation Plan
- Required checks (lint/tests/contracts/log checks): Skill metadata validation, reference/path checks, `git diff --check`, and project skill-discovery verification.
- Expected outcomes: Four architecture skills are available under repository `.agents/skills`; pstack remains the general workflow; multi-step task tracking follows the repository-local policy.
- Dogfooding scenario (real or representative task): Apply the new maintenance skill to an architecture change and verify it checks all three support skills, making updates only where guidance is stale.
- Results: `quick_validate.py` passed for the three moved skills, the new maintainer skill, and both project/global governance skill copies; `git diff --check` passed; governance copies match; no active references to the old three skill locations remain. A representative maintenance pass confirmed this task changes skill locations and routing but not implemented agent architecture, so the three support skills needed no content changes.

## 7) Decision and Ownership
- Skill owner: `architecture-skill-maintainer` and `architecture-standard-enforcer`
- Required approver(s): User
- Decision:
  - [x] Approved
  - [ ] Needs revision
  - [ ] Rejected
- Decision notes: Implemented under the user's explicit direction to make the three skills project-local, add a post-architecture-change maintenance skill, and keep task tracking governed by this project.

## 8) Follow-up
- Implementation PR: Not created in this task.
- Post-merge verification date: 2026-10-20
- Additional actions: Update architecture support skills after future material agent architecture changes.
