# Superseded Checklist

Mark a source doc as `Superseded` only if all checks pass.

## Required Checks
1. Scope replacement exists.
- There is a clear newer owner item/doc covering the same objective.

2. Implementation evidence exists (if claiming completed replacement).
- At least one concrete path from: code, tests, runbook, report, or release gate.

3. No active-only content is lost.
- Any still-pending tasks are moved to `Now/Next/Later/Blocked` in master backlog.

4. No unresolved blockers hidden by archive.
- If blockers remain, do not archive; keep source active or mark review-required.

5. Traceability is preserved.
- Master backlog includes source references and replacement mapping.

## Fail-Safe Rule
- If any check is uncertain, do not archive.
- Keep source as active and add a short review note.
