# Skill Change Request (SCR) Template

Use this template when proposing updates to skills, standards, or playbooks.

## 1) Context
- Request title:
- Date:
- Requestor:
- Related incident/issue/PR links:

## 2) Problem Statement
- What happened?
- Why current skills/standards were insufficient:
- Reproduction signals or evidence (logs, failing checks, screenshots, traces):

## 3) Impact Scope
- Affected area(s):
- Affected modules/paths:
- Severity (P0/P1/P2/P3):
- User/business impact:

## 4) Proposed Skill/Standard Update
- Target category:
  - [ ] Standard (`architecture-standard-enforcer`)
  - [ ] Planner (`architecture-modification-planner`)
  - [ ] Executor (`agent-refactor-executor`)
  - [ ] Debug/Review (`agent-debug-review-playbook`)
- Proposed update summary:
- Exact file(s) to change:
- Why this is generalizable (not case-specific):

## 5) Risk and Compatibility
- Potential false positives/over-constraint risk:
- Backward compatibility considerations:
- Rollback plan:

## 6) Validation Plan
- Required checks (lint/tests/contracts/log checks):
- Expected outcomes:
- Dogfooding scenario (real or representative task):

## 7) Decision and Ownership
- Skill owner:
- Required approver(s):
- Decision:
  - [ ] Approved
  - [ ] Needs revision
  - [ ] Rejected
- Decision notes:

## 8) Follow-up
- Implementation PR:
- Post-merge verification date:
- Additional actions:
