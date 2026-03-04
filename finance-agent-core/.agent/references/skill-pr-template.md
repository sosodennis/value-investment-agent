# Skill Update PR Template

Use this template in PR descriptions when changing any files under `.agent/` skills.

## Summary
- What skill(s) were updated:
- Why this change is needed:
- Linked SCR / incident / issue:

## Scope of Changes
- Files changed:
- Category:
  - [ ] Standard
  - [ ] Planner
  - [ ] Executor
  - [ ] Debug/Review
- Any `agents/openai.yaml` updates:

## Trigger and Generalization
- Trigger case(s):
- Why this should be a reusable rule/workflow (not one-off):

## Validation
- [ ] `quick_validate.py` passed for changed skill(s)
- [ ] Representative dogfooding completed
- [ ] Relevant lint/tests/checks run

Validation details:
- Commands run:
- Results:
- Remaining gaps:

## Risk and Rollback
- Risk level:
- Known side effects:
- Rollback plan:

## Reviewer Checklist
- [ ] Content is concise and non-duplicative
- [ ] Standard vs playbook/planner/executor ownership is correct
- [ ] No case-specific rule leaked into canonical standard
- [ ] References are linked from SKILL.md only as needed
- [ ] Output contracts remain clear and testable

## Post-Merge Follow-up
- Owner:
- Verify date:
- Metrics/signals to watch:
