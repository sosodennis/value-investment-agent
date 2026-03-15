# Skill Change Request (SCR)

## 1) Context
- Request title: Upgrade agent-refactor-executor with consumer contract gates
- Date: 2026-03-14
- Requestor: Dennis Wong
- Related incident/issue/PR links: N/A (recurring refactor friction)

## 2) Problem Statement
- What happened?
  - Refactors that touched artifacts/contracts and frontend consumers required manual coordination; missing consumer updates led to runtime errors and UI regressions.
- Why current skills/standards were insufficient:
  - The executor workflow did not explicitly require a consumer impact map or same-slice contract+consumer updates.
- Reproduction signals or evidence (logs, failing checks, screenshots, traces):
  - INDICATOR SERIES missing in UI; parser/contract mismatch found during technical analysis refactor.

## 3) Impact Scope
- Affected area(s): Refactor execution workflow, cross-surface contract changes
- Affected modules/paths: agent outputs, artifact parsers, UI components
- Severity (P0/P1/P2/P3): P2
- User/business impact: Slower refactor throughput and regressions in visual outputs

## 4) Proposed Skill/Standard Update
- Target category:
  - [ ] Standard (`architecture-standard-enforcer`)
  - [ ] Planner (`architecture-modification-planner`)
  - [x] Executor (`agent-refactor-executor`)
  - [ ] Debug/Review (`agent-debug-review-playbook`)
- Proposed update summary:
  - Add consumer impact map to required inputs; treat output contract changes as high-risk; require same-slice consumer updates and contract test/fixture coverage; add payload-size guard for large time-series artifacts.
- Exact file(s) to change:
  - /Users/denniswong/.codex/skills/agent-refactor-executor/SKILL.md
- Why this is generalizable (not case-specific):
  - Any refactor that changes output contracts or artifacts can break downstream consumers; enforcing a consumer update gate is broadly applicable.

## 5) Risk and Compatibility
- Potential false positives/over-constraint risk:
  - Low; the gate only triggers when outputs change.
- Backward compatibility considerations:
  - Explicitly called out via compatibility stance and consumer updates.
- Rollback plan:
  - Revert skill edits; no runtime impact.

## 6) Validation Plan
- Required checks (lint/tests/contracts/log checks):
  - N/A for skill text change.
- Expected outcomes:
  - Clearer executor workflow reduces consumer regressions.
- Dogfooding scenario (real or representative task):
  - Next refactor involving artifact schema changes.

## 7) Decision and Ownership
- Skill owner: agent-refactor-executor
- Required approver(s): Dennis Wong
- Decision:
  - [x] Approved
  - [ ] Needs revision
  - [ ] Rejected
- Decision notes:
  - Upgrade requested by owner.

## 8) Follow-up
- Implementation PR: N/A (local skill update)
- Post-merge verification date: 2026-03-21
- Additional actions: Consider syncing skills to project mirror if desired.
