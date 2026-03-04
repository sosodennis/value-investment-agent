# Refactor Rollback Playbook

## Trigger Conditions
- Critical validation gate fails and cannot be remediated quickly.
- Hard architecture violation persists after remediation attempt.
- Runtime behavior regresses outside accepted threshold.

## Rollback Procedure
1. Stop additional slice execution.
2. Revert only the current failing slice.
3. Re-run baseline validation checks.
4. Confirm system returns to pre-slice stable state.
5. Record root-cause hypothesis and unresolved blockers.

## Resume Conditions
- Failure cause is isolated.
- Remediation strategy is explicit.
- Updated slice plan remains `small|medium` and verifiable.
