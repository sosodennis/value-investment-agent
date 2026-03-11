# Skill Change Request (SCR): Vertical Slice Refactor Learnings

## 1) Context
- Request title: Generalize vertical-slice refactor lessons into skill templates
- Date: 2026-03-11
- Requestor: Dennis Wong
- Related incident/issue/PR links: N/A (ongoing refactor program)

## 2) Problem Statement
- What happened?
  - Repeated vertical-slice refactors revealed recurring decision points (contract placement, legacy removal, pipeline staging, empty layer cleanup) not captured in skills.
- Why current skills/standards were insufficient:
  - Skills lacked explicit boundary decision rubric, legacy-path sweep requirements, and empty-layer cleanup checks.
- Reproduction signals or evidence (logs, failing checks, screenshots, traces):
  - Refactor reviews repeatedly needed manual checks for old-path imports and empty layer packages.

## 3) Impact Scope
- Affected area(s): Cross-agent refactors and new agent design standards
- Affected modules/paths: `.agent/*` skills (refactor executor, planner, enforcer, debug review, implementation extractor)
- Severity (P0/P1/P2/P3): P3 (maintainability / consistency risk)
- User/business impact:
  - Slower refactor throughput and higher review friction without consistent guidance.

## 4) Proposed Skill/Standard Update
- Target category:
  - [x] Standard (`architecture-standard-enforcer`)
  - [x] Planner (`architecture-modification-planner`)
  - [x] Executor (`agent-refactor-executor`)
  - [x] Debug/Review (`agent-debug-review-playbook`)
  - [x] Implementation Extractor (`agent-implementation-extractor`)
- Proposed update summary:
  - Add boundary decision rubric, propagate explicit subdomain split criteria into planner/executor/enforcer/debug, add legacy-path sweep, empty layer cleanup checks, pipeline staging guidance, and explicit decision logging.
- Exact file(s) to change:
  - `finance-agent-core/.agent/agent-refactor-executor/SKILL.md`
  - `finance-agent-core/.agent/architecture-modification-planner/SKILL.md`
  - `finance-agent-core/.agent/architecture-standard-enforcer/SKILL.md`
  - `finance-agent-core/.agent/agent-debug-review-playbook/SKILL.md`
  - `finance-agent-core/.agent/agent-implementation-extractor/SKILL.md`
- Why this is generalizable (not case-specific):
  - Applies to any agent with vertical-slice subdomains and shared kernel contracts.

## 5) Risk and Compatibility
- Potential false positives/over-constraint risk:
  - Moderate if legacy scans are enforced on unrelated changes; mitigated by scoping to migrations.
- Backward compatibility considerations:
  - No runtime code changes; only skill guidance.
- Rollback plan:
  - Revert skill edits in `.agent/*` and re-sync skills.

## 6) Validation Plan
- Required checks (lint/tests/contracts/log checks):
  - `quick_validate.py` for each changed skill.
- Expected outcomes:
  - All skill validations pass; no YAML or structural errors.
- Dogfooding scenario (real or representative task):
  - Apply updated skills in the next cross-agent refactor or audit plan.

## 7) Decision and Ownership
- Skill owner: Architecture standards (cross-agent)
- Required approver(s): Dennis Wong
- Decision:
  - [x] Approved
  - [ ] Needs revision
  - [ ] Rejected
- Decision notes:
  - Proceed with updates and sync.

## 8) Follow-up
- Implementation PR: TBD
- Post-merge verification date: TBD
- Additional actions: Sync skills to `~/.codex/skills` after approval.
