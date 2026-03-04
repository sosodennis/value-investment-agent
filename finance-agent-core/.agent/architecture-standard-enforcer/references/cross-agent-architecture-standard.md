# Cross-Agent Class Naming and Layer Responsibility Standard

Date: 2026-03-03
Scope: `finance-agent-core/src/agents/*`
Status: Active

This is the canonical cross-agent architecture standard. Keep this file short and enforceable.

## 1. Design Principles

1. Maintainability first: clear ownership, low coupling, readable paths.
2. No compatibility residue: once call sites migrate, remove old routes.
3. No over-design: add abstractions only when they remove real complexity.
4. Typed boundaries over implicit behavior.
5. LOC is a signal, not a target:
   - use high LOC as a review trigger for cohesion/ownership risks
   - do not split purely to hit arbitrary line-count thresholds
   - keep cohesive logic together when a split would increase indirection or reduce readability

## 2. Layer Boundaries (Hard Rules)

1. `domain`
   - Owns deterministic business logic, policies, and contracts.
   - Entity/Value Object vs Domain Service split:
     - if logic depends on one aggregate/value-object state only and has no external I/O, keep behavior on that model owner.
     - use domain service only for cross-entity/aggregate coordination or policy orchestration that does not naturally belong to one model.
   - Must not do network/storage/framework/LLM calls.
2. `application`
   - Owns use-case orchestration and workflow-state routing.
   - Depends on ports/contracts, not concrete infrastructure adapters.
3. `interface`
   - Owns boundary contracts, serialization/mapping, and prompt rendering/specs.
   - Must not import `application` layer DTO/service owners.
   - Must not own domain policy or infrastructure I/O.
   - If workflow/app context mapping is needed, keep the mapper owner in `application`.
4. `infrastructure`
   - Owns provider/client/repository adapters and runtime wiring/config.
   - Repository adapters are storage gateways only; do not mix domain projection/aggregation logic into repository owners.
   - Must not own workflow orchestration or domain policy decisions.

## 3. Naming Contract (Hard Rules)

1. Suffix semantics are mandatory:
   - `*Provider`: single upstream source adapter.
   - `*Repository`: persistence/artifact gateway.
   - `*Client`: low-level transport wrapper.
   - `*Service`: coordination/processing owner.
   - `*Factory`: object assembly only.
   - `*Mapper`: shape transform only.
   - `*Policy`: deterministic rule/threshold policy.
   - `*Port`: protocol/abstraction only (never concrete).
2. File name must match owner role (`*_service.py`, `*_provider.py`, etc.).
3. Do not introduce generic owner modules in mature contexts:
   - avoid `tools.py`, `helpers.py`, `rules.py`, `models.py`, `services.py`.
4. Avoid capability-token stutter inside capability packages:
   - use `contracts.py`, `orchestrator.py`, `*_service.py`, not repeated prefixed names.
5. Prompt content ownership:
   - prompt specs/renderers belong to `interface`, not `domain`.
6. Preview projection naming and ownership:
   - avoid generic `view_models.py` modules in mature agents
   - keep preview projection in `interface` with semantic owner naming (for example `preview_projection_service.py`).

## 4. Capability Packaging Rules

1. One bounded capability -> one canonical package path.
2. Do not split one capability across root-prefixed files plus sibling package.
3. If a capability grows to 4+ tightly-coupled owner modules, group into a dedicated subpackage.
4. For model-builder families, use `per-model subpackages + shared subpackage + parent dispatch/context`.
5. File-size guidance is heuristic only:
   - consider split when a file is both large and multi-responsibility
   - keep single-owner, cohesive modules intact even when LOC is relatively high

## 5. Runtime Wiring and Type Rules

1. Composition/wiring is outside application use-case modules.
2. Avoid long callable bundles (`*_fn`) across orchestrator/use-case chains:
   - inject typed runtime ports instead.
3. Avoid `object`-typed runtime port boundaries when minimal typed contracts are available.
4. `object` is allowed only at boundary decoding/parsing points (typically `interface/parsers`) and must be normalized immediately.
5. `application` runtime boundaries (`ports`, `orchestrator`, `state_readers`) must not keep avoidable `object` types.
6. Infrastructure registry/bootstrap must be explicit or lazy accessor based:
   - no import-time registration side effects.
7. In async use-cases, avoid blocking SDK calls on the event loop:
   - prefer native async APIs (`ainvoke`, async client methods)
   - if only sync API exists, use `asyncio.to_thread(...)` at the boundary.
8. In high-frequency async HTTP adapters/providers, reuse client/session objects:
   - avoid per-request `AsyncClient`/session construction on hot paths
   - expose explicit close hook and wire it into app shutdown lifecycle.
9. External provider degraded outcomes must be typed:
   - do not encode failure as bare `None` without reason metadata.
   - return machine-readable failure info (`failure_code`, optional transport metadata like HTTP status) so use-cases can produce deterministic degraded state and diagnostics.
10. Heavy-compute capability owners (for example Monte Carlo, walk-forward optimization) must expose explicit runtime boundaries:
   - if invoked from async use-cases, do not run compute directly on the event loop.
   - use boundary offload (`asyncio.to_thread(...)`, executor, or dedicated background worker) with bounded concurrency.
11. Heavy-compute changes must include a minimal reproducible performance gate:
   - keep fixed-input benchmark/test baselines (for example seed/window/iterations pinned).
   - enforce a regression threshold so refactors do not silently degrade latency.

## 6. Error Handling and State Rules

1. Fail-fast is allowed at interface/infrastructure boundary parsing.
2. Workflow `state_readers` must be tolerant for optional/partial state:
   - return typed optional values (`None`) instead of raising parse exceptions.
3. Error update contract must stay consistent across agents:
   - `current_node`, `internal_progress`, `node_statuses`, `error_logs`.
   - `error_logs` item shape: `node`, `error`, `severity`.
4. Workflow state entry boundary may remain `Mapping[str, object]` (LangGraph heterogeneous state contract):
   - keep this boundary at node/orchestrator entry only
   - normalize to typed values immediately in `state_readers` and avoid propagating raw state into deeper service contracts.
5. Artifact read semantics must distinguish `not_found` from `empty_payload`:
   - repository/read-boundary owners must not silently normalize missing artifact id/data to empty values (`[]`, `{}`, `""`).
   - missing artifact must surface as explicit failure so use-cases can decide terminal vs degraded behavior deterministically.

## 7. Refactor Migration Rules

1. No long-lived compatibility shim/alias modules.
2. Migrate call sites atomically within a slice whenever feasible.
3. Keep each slice testable and reversible; remove old paths immediately after validation.
4. Add/extend hygiene guards for removed legacy imports/modules.

## 8. Logging Quality Rules

1. Use structured logs only:
   - every event uses a stable `event` name and machine-readable `fields`.
   - avoid free-form logs for state transitions, degradation, and failures.
2. Every node/use-case must emit exactly one start and one completion summary log:
   - start includes key input scope (for example ticker, input count).
   - completion includes output counts and final quality flags (`is_degraded`, `status`).
   - completion summary must be emitted on every terminal return path (success, waiting/degraded, and error), including early-return validation failures.
3. Every degraded/error path must emit a dedicated reason log with `error_code`:
   - include `stage/source`, impact metrics (`input_count`, `output_count`, fallback size), and a short reason string.
   - do not rely on UI `error_logs` state only; backend logs must be independently diagnosable.
4. Fallback behavior must be observable:
   - log `fallback_mode` and fallback selection size/count.
5. Keep logs high-signal and low-noise:
   - no large payload dumps, no duplicated per-item success spam in hot paths.
   - per-item failure logs are allowed if each carries actionable fields (`url`, status/error_code).
6. Keep field naming consistent across agents:
   - prefer `*_count`, `is_degraded`, `error_code`, `node`, `ticker`, `artifact_id`.
7. Exception text in logs should be bounded (truncated) to avoid oversized noisy events.

## 9. Minimal PR Checklist

1. Does each changed module have a single clear owner responsibility?
2. Any concrete class still named `*Port`?
3. Any application/domain import concrete infrastructure?
4. Any generic catch-all module introduced?
5. Any capability split across two parallel package routes?
6. Any import-time bootstrap side effect introduced?
7. Any runtime boundary still using avoidable `object` types?
8. Any prompt or narrative formatting left in domain?
9. Are error updates still in the unified contract shape?
10. Are state readers still resilient (no optional-state exception leakage)?
11. Were compatibility paths removed after call-site migration?
12. Did this change improve maintainability without unnecessary abstraction?
13. Any preview projection logic left in `application/view_models.py` instead of `interface` projection owner?
14. Any repository adapter mixing persistence I/O with domain projection/aggregation logic?
15. Any avoidable `object` type left in `application` runtime boundaries (outside parser decoding boundary and workflow-state entry boundary)?
16. Any async node/use-case still doing blocking sync network/LLM calls on the event loop?
17. Are start/completion/degraded logs present and structured for the changed node/use-case?
18. Are degraded/error logs carrying machine-readable reason and impact metrics (not only free-text)?
19. Any repository/read boundary silently converting missing artifact to empty payload?
20. Any high-frequency async adapter still creating per-request client/session objects without lifecycle-managed reuse?
21. Any external provider still returning bare `None` for degraded failures where typed failure metadata is required for state/log diagnostics?
22. Any `interface` module importing `application` owners (DTO/services/context mappers)?
23. Is deterministic logic placed on the right owner (entity/value object vs domain service) per single-aggregate vs cross-entity rule?
24. Any heavy compute path inside async use-cases still running directly on the event loop?
25. For changed heavy-compute code, is the reproducible performance baseline/test updated and within threshold?

## 10. Standard Update Policy

Update this file only when a new anti-pattern class appears in real code. Do not add case-specific rules that do not generalize across agents.
