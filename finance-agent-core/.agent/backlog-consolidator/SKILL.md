---
name: backlog-consolidator
description: Consolidate multiple backlog/planning documents into one master backlog artifact, deduplicate overlapping items, classify status (Now/Next/Later/Blocked/Done/Superseded), and archive only evidence-backed superseded docs. Use when parallel tasks across domains or agents create fragmented backlogs and you need a periodic sync without starting implementation.
---

# Backlog Consolidator

## Overview
Generate a single execution-oriented backlog artifact from scattered planning docs.
Keep traceability to source docs, but treat the generated master artifact as the execution authority for the current cycle.

## Workflow
1. Normalize request scope.
- Confirm the domain scope (single module, multi-module, or repo-wide).
- Confirm cadence (daily/weekly/bi-weekly) and output mode.
- Default output mode is artifact text for manual paste unless asked to auto-edit files.

2. Build source inventory.
- List all backlog/planning docs in scope.
- Mark each source as `active_candidate` or `review_candidate`.
- Load [references/cadence-checklist.md](references/cadence-checklist.md) to enforce cycle hygiene.

3. Extract and deduplicate work items.
- Normalize each item into: `id`, `title`, `status`, `source`, `exit_criteria`.
- Merge overlapping items by outcome, not by wording.
- If two items conflict, keep one canonical item and add conflict note.

4. Verify superseded candidates with evidence.
- Use [references/superseded-checklist.md](references/superseded-checklist.md).
- Require concrete evidence paths (code/tests/runbook/report) before marking `Superseded`.
- If evidence is incomplete, do not archive; keep item in `Next` or `Blocked`.

5. Produce master backlog artifact.
- Use [references/master-backlog-template.md](references/master-backlog-template.md).
- Fill only supported statuses: `Now`, `Next`, `Later`, `Blocked`, `Done`, `Superseded`.
- Keep items short and execution-oriented.

6. Archive source docs only when explicitly requested.
- Archive only docs marked `Superseded` with verified evidence.
- Never archive `active` docs.
- Keep original files unchanged except location move.

7. Return handoff summary.
- List created/updated artifact paths.
- List archived docs.
- List unresolved conflicts or open assumptions.

## Output Rules
- Do not start implementation work while consolidating.
- Do not rewrite technical details in source docs; summarize and link back.
- Keep one execution authority per cycle: the generated master backlog artifact.
- If uncertain between `Done` and `Superseded`, choose `Done` plus note; do not archive.

## Resources
- Template: [references/master-backlog-template.md](references/master-backlog-template.md)
- Superseded gate: [references/superseded-checklist.md](references/superseded-checklist.md)
- Cycle gate: [references/cadence-checklist.md](references/cadence-checklist.md)
