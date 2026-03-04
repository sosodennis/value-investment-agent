# Skill Change Request (SCR)

## 1) Context
- Request title: Intent multi-source degraded observability review gap
- Date: 2026-03-04
- Requestor: Dennis Wong / Codex execution follow-up
- Related incident/issue/PR links:
  - Runtime evidence: `docs/logs/intent.log`
  - Refactor tracker: `docs/backlog/intent_extraction_clean_architecture_refactor_blueprint.md`

## 2) Problem Statement
- What happened?
  - Intent search used Yahoo + web dual channel; web channel failed/empty but node completion was still reported as fully healthy in prior implementation.
- Why current skills/standards were insufficient:
  - Canonical standard already requires degraded observability, but debug/review playbook did not explicitly call out the "channel-level failure masked by overall success" audit step for multi-source nodes.
- Reproduction signals or evidence (logs, failing checks, screenshots, traces):
  - `intent_web_search_failed` present while search stage still completed successfully.
  - Historical symptom (before fix): completion quality flag could remain healthy despite fallback.

## 3) Impact Scope
- Affected area(s): intent extraction search stage observability and review methodology
- Affected modules/paths:
  - `src/agents/intent/application/orchestrator.py`
  - `src/agents/intent/infrastructure/search/ddg_web_search_provider.py`
  - `.agent/agent-debug-review-playbook/SKILL.md`
- Severity (P0/P1/P2/P3): P2
- User/business impact:
  - Potential false health signal in runtime monitoring; slower root-cause triage for partial quality degradation.

## 4) Proposed Skill/Standard Update
- Target category:
  - [ ] Standard (`architecture-standard-enforcer`)
  - [ ] Planner (`architecture-modification-planner`)
  - [ ] Executor (`agent-refactor-executor`)
  - [x] Debug/Review (`agent-debug-review-playbook`)
- Proposed update summary:
  - Add explicit multi-source observability check to debug/review workflow: when any channel degrades and fallback is used, completion quality flags and degraded reason logs must reflect quality drop.
- Exact file(s) to change:
  - `finance-agent-core/.agent/agent-debug-review-playbook/SKILL.md`
- Why this is generalizable (not case-specific):
  - Multi-source/fallback patterns exist across agents (news search funnel, technical external data, intent dual-channel search).

## 5) Risk and Compatibility
- Potential false positives/over-constraint risk:
  - Low; this is a review checklist enhancement, not a new hard architecture rule.
- Backward compatibility considerations:
  - None; no runtime contract break from skill update.
- Rollback plan:
  - Revert the single bullet added to `agent-debug-review-playbook/SKILL.md`.

## 6) Validation Plan
- Required checks (lint/tests/contracts/log checks):
  - Runtime/code checks: `ruff` + intent targeted pytest suite.
  - Skill checks: `quick_validate.py` on changed skill directory.
- Expected outcomes:
  - Runtime: all targeted intent checks pass.
  - Skill: validation script returns "Skill is valid!"
- Dogfooding scenario (real or representative task):
  - Real run: inspect `docs/logs/intent.log` post-refactor and verify degraded observability + severity semantics.

## 7) Decision and Ownership
- Skill owner: `agent-debug-review-playbook`
- Required approver(s): project maintainer
- Decision:
  - [x] Approved
  - [ ] Needs revision
  - [ ] Rejected
- Decision notes:
  - Standard text already sufficient; playbook needed explicit reusable audit step.

## 8) Follow-up
- Implementation PR:
  - local working tree changes (not yet committed in this run)
- Post-merge verification date:
  - 2026-03-04
- Additional actions:
  - Continue monitoring logs for channel-level degraded propagation consistency.

---

# Skill Update PR Checklist (Draft)

## Summary
- What skill(s) were updated:
  - `.agent/agent-debug-review-playbook/SKILL.md`
- Why this change is needed:
  - Ensure debug/review workflow catches "channel degraded but overall success" observability gaps.
- Linked SCR / incident / issue:
  - This document (SCR section above), `docs/logs/intent.log`

## Scope of Changes
- Files changed:
  - `finance-agent-core/.agent/agent-debug-review-playbook/SKILL.md`
- Category:
  - [ ] Standard
  - [ ] Planner
  - [ ] Executor
  - [x] Debug/Review
- Any `agents/openai.yaml` updates:
  - No

## Trigger and Generalization
- Trigger case(s):
  - intent dual-channel search fallback observability mismatch surfaced during log audit.
- Why this should be a reusable rule/workflow (not one-off):
  - Any multi-source pipeline can show the same mismatch.

## Validation
- [x] `quick_validate.py` passed for changed skill(s)
- [x] Representative dogfooding completed
- [x] Relevant lint/tests/checks run

Validation details:
- Commands run:
  - `python3 /Users/denniswong/.codex/skills/.system/skill-creator/scripts/quick_validate.py finance-agent-core/.agent/agent-debug-review-playbook`
  - `uv run --project finance-agent-core python -m ruff check ...`
  - `uv run --project finance-agent-core python -m pytest ...`
- Results:
  - skill validate pass; runtime checks pass.
- Remaining gaps:
  - none identified in current scope.

## Risk and Rollback
- Risk level: Low
- Known side effects: None
- Rollback plan: Revert skill bullet update.

## Reviewer Checklist
- [x] Content is concise and non-duplicative
- [x] Standard vs playbook/planner/executor ownership is correct
- [x] No case-specific rule leaked into canonical standard
- [x] References are linked from SKILL.md only as needed
- [x] Output contracts remain clear and testable

## Post-Merge Follow-up
- Owner: project maintainer
- Verify date: 2026-03-04
- Metrics/signals to watch:
  - frequency of channel-level degraded-but-success mismatches in agent logs
