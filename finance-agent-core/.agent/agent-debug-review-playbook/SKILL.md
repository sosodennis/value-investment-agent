---
name: agent-debug-review-playbook
description: Run a structured debugging and review workflow for agent modules. Use when investigating runtime failures, degraded paths, regressions, flaky behavior, or post-refactor quality risks, and when you need severity-ranked findings, likely root causes, minimal remediation direction, and validation coverage.
---

# Agent Debug Review Playbook

## Purpose

Diagnose agent failures and regressions quickly with architecture-aware review discipline.
Produce actionable findings, not broad speculative rewrites.

## Workflow

1. Triage and reproduction.
- Capture symptom, impact, and reproducibility.
- Pin the failing node/use-case and minimal reproduction path.

2. Boundary isolation.
- Isolate failure by layer and owner (`domain/application/interface/infrastructure`).
- Identify whether the issue is contract, runtime, data-shape, async, or dependency drift.

3. Evidence collection.
- Collect stack traces, logs, state snapshots, and contract mismatches.
- Validate whether degraded behavior is typed and observable.

4. Root-cause hypothesis and verification.
- Rank hypotheses by likelihood and blast radius.
- Validate with focused checks; eliminate alternatives.

5. Severity-ranked findings.
- Report each confirmed issue with file/line and impact.
- Link to violated standard section when architecture rules are involved.

6. Remediation direction.
- Propose minimal, maintainable remediation steps.
- Call out migration risks and compatibility considerations.

7. Validation plan.
- Define exact checks needed to confirm remediation.
- Include residual risk and coverage gaps if unresolved.

## Severity Baseline

- `P0`: production outage/data corruption/security impact.
- `P1`: major functional break or deterministic incorrect behavior.
- `P2`: moderate defect or degraded quality with bounded impact.
- `P3`: low-impact issue, maintainability/readability risk.

## Output Contract

Use this report structure:
- `Findings`: prioritized list with severity, file/line, impact, and evidence.
- `Assumptions/Open Questions`: only unresolved blockers.
- `Applied Changes`: only if edits were made.
- `Validation`: checks run, results, and remaining gaps.

## Guardrails

- Keep findings evidence-based.
- Distinguish confirmed cause from hypothesis.
- Prefer the smallest reliable remediation path.
