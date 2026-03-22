# Skill Change Request (SCR)

## 1) Context
- Request title: Add signature-change guard to agent-refactor-executor
- Date: 2026-03-22
- Requestor: denniswong
- Related incident/issue/PR links: Stream runtime error (TypeError: event_generator positional args mismatch) during refactor rollout

## 2) Problem Statement
- What happened?
  - A refactor introduced a function signature change, but a call site still passed positional arguments, causing a runtime TypeError in `/app/api/server.py` during streaming.
- Why current skills/standards were insufficient:
  - The executor workflow did not explicitly require a signature-change sweep or call-site audit when changing function parameters.
- Reproduction signals or evidence (logs, failing checks, screenshots, traces):
  - `TypeError: event_generator() takes 4 positional arguments but 5 positional arguments (and 2 keyword-only arguments) were given`

## 3) Impact Scope
- Affected area(s): Streaming API runtime, refactor execution safety
- Affected modules/paths:
  - `finance-agent-core/api/server.py`
  - `finance-agent-core/src/interface/events/adapters.py`
- Severity (P0/P1/P2/P3): P2
- User/business impact:
  - Streaming requests failed at runtime; degraded user experience and confidence in refactor safety.

## 4) Proposed Skill/Standard Update
- Target category:
  - [ ] Standard (`architecture-standard-enforcer`)
  - [ ] Planner (`architecture-modification-planner`)
  - [x] Executor (`agent-refactor-executor`)
  - [ ] Debug/Review (`agent-debug-review-playbook`)
- Proposed update summary:
  - Add a signature-change guard: when altering function signatures, require a call-site sweep, prefer keyword-only for new params, and add a minimal smoke validation to catch positional mismatch.
- Exact file(s) to change:
  - `~/.codex/skills/agent-refactor-executor/SKILL.md`
  - Mirror via `finance-agent-core/scripts/sync_skills.sh`
- Why this is generalizable (not case-specific):
  - Signature changes are a common refactor risk; a simple guard reduces runtime breakage across all refactors.

## 5) Risk and Compatibility
- Potential false positives/over-constraint risk:
  - Low; this adds a small checklist item and optional smoke validation.
- Backward compatibility considerations:
  - None (skill/process change only).
- Rollback plan:
  - Revert the skill update and resync skills.

## 6) Validation Plan
- Required checks (lint/tests/contracts/log checks):
  - `quick_validate.py` for changed skill(s) (if available)
- Expected outcomes:
  - Skill validation passes; new guidance is concise and actionable.
- Dogfooding scenario (real or representative task):
  - Apply on next refactor involving signature changes; verify call-site sweep prevents mismatched positional arguments.

## 7) Decision and Ownership
- Skill owner: agent-refactor-executor
- Required approver(s): denniswong
- Decision:
  - [x] Approved
  - [ ] Needs revision
  - [ ] Rejected
- Decision notes:
  - Add minimal signature-change guard with keyword-only preference.

## 8) Follow-up
- Implementation PR:
  - Local skill update + sync (no external PR yet)
- Post-merge verification date:
  - 2026-03-29
- Additional actions:
  - Ensure sync keeps `.agent` mirrors aligned.
