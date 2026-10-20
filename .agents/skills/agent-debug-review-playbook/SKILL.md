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
- Isolate failure by owner (`entrypoint/workflow/application/domain/capability/infrastructure/interface`).
- Identify whether the issue is contract, runtime, data-shape, async, or dependency drift.
- Check canonical import directions and whether the root graph reaches into agent internals.
- Treat `subdomains/`, root `src/workflow/nodes/<agent>/`, and `application/subgraph.py` as migration-era paths when present; compare observed placement with the target standard.

3. Evidence collection.
- Collect stack traces, logs, state snapshots, and contract mismatches.
- Validate whether degraded behavior is typed and observable.
- Check for import cycles and new architecture-guard violations. Existing exact exceptions are migration work, not approval for new edges; use their action IDs in `src/agents/ARCHITECTURE_MODULE_ACTIONS.md`.
- Sweep for private capability imports, cross-agent internals, and root workflow imports that bypass `entrypoint.py`.
- For graph changes, run the focused fake-adapter entrypoint test and confirm graph input/output schemas. Build through the public entrypoint with an injected runner; test a temporary `application/subgraph.py` bridge separately only while a root caller still depends on it.
- For runtime quality checks (similarity/scoring/consensus detectors), verify input provenance:
  - confirm reader path matches writer path in workflow state.
  - confirm logs expose bounded input diagnostics (for example text length/hash) to detect empty/wrong-source inputs.
- For multi-source nodes, verify completion quality flags align with channel-level failures/fallbacks:
  - if any upstream channel fails or returns empty unexpectedly and fallback is used, completion should reflect quality degradation (`is_degraded=true`) and emit a machine-readable degrade reason log.

4. Root-cause hypothesis and verification.
- Rank hypotheses by likelihood and blast radius.
- Validate with focused checks; eliminate alternatives.

5. Severity-ranked findings.
- Report each confirmed issue with file/line and impact.
- Link to violated standard section when architecture rules are involved.

6. Remediation direction.
- Propose minimal, maintainable remediation steps.
- Call out migration risks and compatibility considerations.
- Prefer moving the smallest unit (function/contract) over broad rewrites.

7. Validation plan.
- Define exact checks needed to confirm remediation.
- Include residual risk and coverage gaps if unresolved.

## Capability Boundary Diagnostic Lens

- Use when boundary leaks, circular imports, or ownership confusion appear after refactors.
- Evaluate whether a missing or over-split capability boundary is the root cause using the criteria below.
- **Capability boundary**: a coherent capability has a stable API and can evolve independently.
- **Dependency boundary**: distinct external dependencies or data sources justify a separate subdomain.
- **Pipeline boundary**: multi-stage pipelines (fetch/extract/map/score/postprocess) benefit from stage grouping or subdomain split.
- **Ownership boundary**: different teams or lifecycles need isolated changes and tests.
- **Cohesion signal**: a cohesive set of owner modules changes together and has a stable public contract.
- **Do not split** if it only reduces LOC or increases indirection without clear boundary value.
- Prefer `capabilities/` for new packages; record existing `subdomains/` as legacy placement.

## Cohesion/Facade Diagnostic Lens

- Use when refactors introduce deep imports, long import paths, or difficult traceability.
- Assess over-fragmentation, missing capability facade exports, and cross-capability cycles; propose consolidation or a stable facade.
- Validate against `$architecture-standard-enforcer` cohesion/facade standards.

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
