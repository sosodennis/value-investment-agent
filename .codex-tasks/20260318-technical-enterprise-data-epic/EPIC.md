# EPIC: Technical Enterprise Data Surface Upgrade

## Goal
Upgrade the technical agent from a collection of usable deterministic artifacts into an enterprise-grade technical data surface with hardened contracts, reusable evidence, policy alerts, and frontend-ready quality semantics.

## Scope
- T31: Harden technical artifact contracts and indicator metadata/provenance.
- T32: Build a normalized technical evidence layer for multi-consumer reuse.
- T33: Upgrade alerts from static thresholds to policy alerts with evidence refs.
- T34: Extend technical report/schema/frontend parsers for evidence, quality, and alerts.
- T35: Upgrade frontend technical UI to render evidence, quality coverage, and policy alerts.
- T36: Add observability summaries, contract validation, and rollout hygiene.

## Constraints
- No compatibility shims.
- Preserve current root topology: `application / domain / interface / subdomains`.
- Prefer additive contract migration and synchronized frontend rollout.
- Do not introduce new paid-data dependencies or new technical subdomains.

## Non-Goals
- Rework fusion policy.
- Add Anchored VWAP or new advanced market-data capabilities.
- Redesign the entire technical frontend layout.

## Risk Assessment
- Contract expansion risk: backend artifact schemas and frontend generated types/parsers must stay synchronized.
- Migration risk: loose `dict[str, object]` fields are spread across multiple artifacts and projections.
- UX risk: evidence/quality data can overload the frontend if not progressively disclosed.
- Governance risk: evidence layer can become another loose blob if not kept strongly typed from the start.

## Child Deliverables
- Contract hardening for timeseries/indicator/feature/pattern/regime/fusion metadata.
- Normalized evidence bundle and semantic/report projection migration.
- Policy-based alert contract and runtime upgrade.
- Frontend parser/type/API contract alignment.
- Frontend UI evidence/quality/alerts rendering.
- Observability summaries and validation hardening.

## Dependency Notes
- T32 depends on T31 because evidence should consume hardened contracts instead of raw dict payloads.
- T33 depends on T31 and T32 because policy alerts should cite typed evidence and quality metadata.
- T34 depends on T31 and T32 because report/frontend contracts should expose the new deterministic evidence surface.
- T35 depends on T34 and T33 so the UI can render finalized contract fields and policy alerts.
- T36 depends on all prior child tasks to validate rollout hygiene and observability completeness.

## Child Task Types
- `single-compact`
- `single-full`
- `batch`

## Done-When
- [ ] Every row in `SUBTASKS.csv` is `DONE`
- [ ] Backend targeted contract/application tests pass
- [ ] Frontend parser/type tests pass
- [ ] Final epic validation passes
