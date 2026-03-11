---
name: architecture-standard-enforcer
description: Enforce canonical cross-agent architecture compliance for finance-agent-core/src/agents/* and directly affected boundary modules. Use when reviewing PRs, auditing existing code for standard violations, planning refactors before implementation, or validating post-refactor compliance for layer boundaries, naming contracts, runtime/type boundaries, async behavior, error/state contracts, structured logging, and migration hygiene.
---

# Architecture Standard Enforcer

## Required Reference

Read `references/cross-agent-architecture-standard.md` before analysis.
Treat hard rules as blocking unless the user explicitly requests a temporary exception.

## Workflow

1. Scope the slice.
- Focus on `finance-agent-core/src/agents/*` and directly affected boundary modules.
- Ignore unrelated files unless coupling or import direction is impacted.

2. Map ownership and layer boundaries.
- Classify each changed module as `domain`, `application`, `interface`, or `infrastructure`.
- Flag cross-layer leakage and wrong owner placement.

3. Enforce naming and packaging contracts.
- Validate class suffix semantics and filename-role consistency.
- Flag generic catch-all modules in mature paths.
- Flag empty layer packages (`application/`, `domain/`, `interface/`, `infrastructure`).

4. Validate runtime/type/async boundaries.
- Flag avoidable `object` propagation beyond allowed decode/state-entry boundaries.
- Flag blocking sync I/O or heavy compute on async event-loop paths.
- Flag missing lifecycle-managed client/session reuse in hot async adapters.

5. Validate error/state/logging contracts.
- Check unified error update shape and resilient state readers.
- Distinguish artifact `not_found` vs `empty_payload`.
- Require typed degraded outcomes (not bare `None`) for providers.
- Require structured start/completion/degraded logs with machine-readable fields.

6. Validate migration hygiene.
- Ensure call-site migration is atomic per slice when feasible.
- Remove compatibility shims/aliases after migration validation.
- Add hygiene guards for removed legacy imports/modules when relevant.
- Scan for legacy path imports after refactors (old → new path).
- Ensure pipeline-heavy infrastructure is grouped by stage when applicable.
- Confirm preview/projection contracts live in `interface`, not `domain`.

7. Report findings and remediation direction.
- Rank findings by severity.
- Recommend the smallest maintainable remediation path.
- State residual risks and test gaps.

## Subdomain Split Enforcement

- Apply when a change introduces or removes a subdomain.
- Validate justification using the criteria below and flag violations as findings.
- **Capability boundary**: a coherent capability has a stable API and can evolve independently.
- **Dependency boundary**: distinct external dependencies or data sources justify a separate subdomain.
- **Pipeline boundary**: multi-stage pipelines (fetch/extract/map/score/postprocess) benefit from stage grouping or subdomain split.
- **Ownership boundary**: different teams or lifecycles need isolated changes and tests.
- **Cohesion signal**: 4+ tightly-coupled owner modules in one area that change together repeatedly.
- **Do not split** if it only reduces LOC or increases indirection without clear boundary value.

## Cohesion and Facade Standards

- Apply when deep imports or fine-grained modules appear after refactors.
- Flag over-fragmentation: multiple single-purpose modules only used together in one workflow path.
- Require facade exports for deep internals: external imports should target subdomain top-level or explicit `application`/`interface` entrypoints, not deep `infrastructure/...` or `.../extract/...`.
- Allow deep nesting only for pipeline-stage grouping (fetch/extract/map/score/postprocess); otherwise flatten or add a facade.
- Do not expose internal stage modules outside their subdomain.

## Output Contract

Use this report structure:
- `Findings`: severity-ordered list with file/line and violated rule section.
- `Assumptions/Open Questions`: only when blockers remain.
- `Applied Changes`: only if edits were made.
- `Validation`: checks executed, or explicit statement if not run.

## Guardrails

- Do not invent new standards; enforce the canonical reference.
- Keep findings actionable and specific.
- Prefer minimal, maintainable fixes over broad rewrites.
