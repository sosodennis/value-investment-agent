# Next Refactor Pending
Date: 2026-02-16
Scope: `finance-agent-core/src/agents/*`, `finance-agent-core/src/workflow/**`
Policy Baseline: Simple Triad + strict typed boundary + strict naming.

This is the single source of truth for open refactor work.

## Status Update (2026-02-16)

1. P0-1 progress:
   - Intent clarification/search/decision boundary serialization moved into application/interface.
   - Debate report reader enforces model -> JSON DTO conversion at data boundary.
   - News fetch path removed duck-typing fallback; fetch payload path now uses typed `NewsSearchResultItemModel`.
2. P0-2 progress:
   - Added/updated boundary regression tests for intent/news/fundamental/technical.
   - Debate boundary regression already covered by `test_debate_report_reader.py`.
3. P0-3 progress:
   - Workflow nodes (`intent/news/technical`) are now thin routers and no longer assemble boundary payloads inline.
   - Status message payload assembly moved from workflow nodes into orchestrators.
4. P1-1 progress:
   - Debate special-case mapper module `interface/verdict_mappers.py` has been merged into canonical `interface/mappers.py`.
   - News prompt transport formatting has been renamed to `interface/prompt_renderers.py` to align with explicit renderer naming.
   - Removed dead `fundamental/interface/report_helpers.py` to reduce naming noise.
   - Fundamental orchestrator removed pure pass-through wrappers and now depends directly on canonical mapper/serializer/domain functions.
5. P1-2 progress:
   - Debate `application/use_cases.py` has been renamed to `application/debate_service.py`.
   - Orchestrator imports now point to `debate_service.py`, removing one legacy `use_cases.py` entrypoint.
   - Intent `application/use_cases.py` has been renamed to `application/intent_service.py`.
   - Fundamental `application/use_cases.py` has been renamed to `application/fundamental_service.py`.
6. P1-3 progress:
   - News/Intent/Technical prompt runtime message rendering now lives in `interface/prompt_renderers.py`.
   - Debate workflow nodes no longer import domain prompt constants; prompt wiring is centralized in `debate/application/factory.py`.
   - Removed unused `news/interface/prompts.py` compatibility layer.
7. P2-4 progress:
   - Added unified boundary incident logger at `src/shared/kernel/tools/incident_logging.py`.
   - Standard schema keys are now emitted in key paths: `node`, `artifact_id`, `contract_kind`, `error_code`.
   - Added minimal replay diagnostics snapshot (`replay`) and attached it to boundary error logs.
   - Hardened `news` aggregator boundary to fail safely with structured diagnostics instead of raw traceback.
8. P2-5 progress:
   - Removed unused package-level facade imports in fundamental orchestrator.
   - Reduced dead `__init__.py` re-export surfaces across unused agent package layers.
9. P3-1 progress:
   - Added `docs/developer-workflow-checklist.md` with triad placement checklist, boundary checklist, and incident triage steps.

## P0 (Must Do First)

1. Remove remaining mixed model/dict cross-boundary paths. (Done)
   - Rule: Domain/Application internal flow must stay typed models.
   - Rule: Cross-agent contract/workflow state/artifact JSON must stay DTO dict.
   - Boundary conversion is allowed exactly once in interface/data adapter.
2. Add regression tests for boundary shape invariants on every agent. (Done)
   - Assert no `model.get(...)` style assumptions in flows that may receive Pydantic models.
   - Assert adapter outputs for cross-agent payload are JSON DTO (`dict`/`list[dict]`).
3. Complete workflow node thinning. (Done)
   - Nodes only call application orchestrator/factory entrypoints.
   - No inline mapping/serialization/model validation logic in nodes.

## P1 (Next Wave)

1. Continue naming convergence to Simple Triad vocabulary. (Done)
   - Request/response mapping: `interface/{parsers,serializers,mappers}.py`
   - Local store mapping: `data/{ports,mappers}.py`
   - Cross-agent contract mapping: `interface/contracts.py` + `interface/{parsers,serializers,mappers}.py`
2. Reduce legacy `use_cases.py` indirection where it acts as alias/re-export only. (Done)
   - Prefer direct `orchestrator.py`, `*_service.py`, `state_readers.py`, `state_updates.py`.
3. Finalize prompt ownership consistency. (Done)
   - Business prompt rules in `domain/prompt_builder.py`.
   - Provider/runtime rendering in `interface/prompt_renderers.py`.

## P2 (Stability / Safety)

1. P2-4 Observability & Incident Safety. (Done)
   - Unified boundary log schema across key orchestrator boundaries.
   - Replay diagnostics snapshot is included for non-`OK` boundary events.
2. P2-5 Technical Debt Cleanup. (Done)
   - Dead package re-exports and unused facade imports removed.
   - `__init__.py` API surface reduced to canonical entrypoints or package markers.

## P3 (Developer Workflow)

1. P3-1 Developer Workflow baseline. (Done)
   - Added actionable checklist for boundary-safe refactors and incident triage.

## Remaining Pending

1. No open P0/P1/P2/P3 items in this file.
2. Next phase should start a new backlog file with new scope/date.

## Definition of Done

1. No runtime crashes from model/dict mixing in cross-agent paths.
2. Workflow nodes are orchestration-only.
3. Each mapping function is classifiable as exactly one of:
   - request/response mapping
   - local store mapping
   - cross-agent contract mapping
4. New changes pass boundary tests and quality gates in one PR.
