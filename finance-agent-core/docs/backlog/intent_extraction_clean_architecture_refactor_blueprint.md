# Intent Extraction Clean Architecture Refactor Blueprint

Date: 2026-03-04
Scope: `finance-agent-core/src/agents/intent`
Status: Proposed (Ready for implementation)
Policy baseline:
1. `finance-agent-core/docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
2. `finance-agent-core/docs/standards/refactor_lessons_and_cross_agent_playbook.md`

## Requirement Breakdown

Objectives:
1. Review and refactor `intent` to strict clean architecture alignment.
2. Detect and remove leftovers from the historical split (`intent` previously coupled with `fundamental` era).
3. Keep maintainability/readability/robustness as first priority, without over-design.
4. Do not keep long-lived compatibility paths.

Constraints:
1. This blueprint is planning-only (no code in this phase).
2. Refactor should prefer larger, atomic slices.
3. Directly impacted boundary modules may be included (`workflow/nodes/intent_extraction/*`, `workflow/state.py`, `tests/*intent*`).

Non-goals:
1. No functional strategy changes to intent business semantics unless required by architecture correctness.
2. No refactor of `debate` in this slice.

## Findings

Severity order, with violated standard section:

1. P1 - Application layer depends directly on infra + import-time side effect.
   - Files:
     - `src/agents/intent/application/intent_service.py`
   - Evidence:
     - direct infra call: `get_llm` import from global infrastructure provider
     - import-time side effect: `load_dotenv(find_dotenv())`
   - Violations:
     - Layer Boundaries (`application` should depend on ports/contracts)
     - Runtime Wiring (`no import-time registration/side effects`)

2. P1 - External adapters live in `data` and degraded outcome is bare `None`.
   - Files:
     - `src/agents/intent/data/market_clients.py`
   - Evidence:
     - external I/O owner package is `data/*` instead of `infrastructure/*`
     - `get_company_profile` returns `None` for failures, losing failure semantics
   - Violations:
     - Layer ownership/naming contract
     - Typed degraded outcomes requirement

3. P1 - Prompt specification owner in `domain`.
   - Files:
     - `src/agents/intent/domain/prompt_builder.py`
   - Violations:
     - Prompt content ownership rule (`interface`, not `domain`)

4. P2 - Orchestrator dependency shape is callable-bundle heavy; boundary types too broad.
   - Files:
     - `src/agents/intent/application/orchestrator.py`
     - `src/agents/intent/application/factory.py`
   - Evidence:
     - multiple `*_fn` runtime dependencies and `object` boundaries propagated in application
   - Violations:
     - Runtime wiring/type rules (typed runtime ports over long callable bundles)

5. P2 - Compatibility residue in interrupt resume parsing.
   - Files:
     - `src/agents/intent/interface/parsers.py`
     - `src/agents/intent/application/orchestrator.py`
   - Evidence:
     - accepts both `selected_symbol` and legacy `ticker`
   - Violations:
     - Migration hygiene (remove compatibility residue after migration)

6. P2 - Logging completion contract not fully symmetric for all terminal paths.
   - Files:
     - `src/agents/intent/application/orchestrator.py`
   - Evidence:
     - structured `started` logs exist, but completion summary is not consistently emitted across all terminal branches of each node.
   - Violations:
     - Logging Quality Rules (start + completion on all terminal paths)

7. P2 - Split-cleanup residue in tests (old module import path).
   - Files:
     - `tests/test_intent_mapper.py`
   - Evidence:
     - imports `src.agents.intent.domain.report_contracts` (module no longer exists)
   - Violations:
     - Migration hygiene and baseline test integrity

## Technical Objectives and Strategy

1. Architecture convergence:
   - Move external I/O owners from `data` to `infrastructure`.
   - Keep `application` orchestration-only with typed runtime ports.
   - Move prompt specification ownership to `interface`.

2. Runtime/type convergence:
   - Replace long callable bundles with minimal typed runtime ports.
   - Keep `Mapping[str, object]` only at workflow entry boundaries; normalize immediately.

3. Migration hygiene:
   - Remove legacy compatibility input (`ticker` in clarification resume path).
   - Remove old import paths in tests and ensure no residual compatibility alias is kept.

4. Observability hardening:
   - Add symmetric completion summary logs for extraction/searching/decision/clarifying terminal paths.

Implementation principle:
1. Large but atomic slices.
2. No over-abstraction: introduce only minimum ports needed to remove cross-layer leakage.

## Involved Files

Directly involved (high confidence):
1. `src/agents/intent/application/factory.py`
2. `src/agents/intent/application/intent_service.py`
3. `src/agents/intent/application/orchestrator.py`
4. `src/agents/intent/data/market_clients.py`
5. `src/agents/intent/domain/prompt_builder.py`
6. `src/agents/intent/interface/parsers.py`
7. `src/agents/intent/interface/prompt_renderers.py`
8. `src/agents/intent/subgraph.py`
9. `src/workflow/nodes/intent_extraction/nodes.py`
10. `src/workflow/nodes/intent_extraction/subgraph_state.py`
11. `tests/test_intent_mapper.py`
12. `tests/test_error_handling_intent.py`
13. `tests/test_intent_interface_parsers.py`
14. `tests/test_interrupts.py`

Expected new files (planned):
1. `src/agents/intent/application/ports.py`
2. `src/agents/intent/infrastructure/market_data/yahoo_ticker_search_provider.py`
3. `src/agents/intent/infrastructure/market_data/company_profile_provider.py`
4. `src/agents/intent/infrastructure/search/ddg_web_search_provider.py`
5. `src/agents/intent/infrastructure/llm/intent_extraction_provider.py`
6. `src/agents/intent/interface/prompt_specs.py`
7. `src/agents/intent/wiring.py`

Expected removals after migration:
1. `src/agents/intent/data/market_clients.py`
2. `src/agents/intent/domain/prompt_builder.py`

## Detailed Per-File Plan

### Phase P0: Baseline unblock + residue scan
1. Fix stale test imports:
   - Replace `src.agents.intent.domain.report_contracts` with canonical owner (`domain.models`).
2. Add grep-based residue checks in execution notes:
   - legacy tokens: `report_contracts`, legacy resume `ticker` fallback.
3. Exit criteria:
   - intent test collection passes.

### Phase P1: Layer ownership convergence (largest slice)
1. Introduce `application/ports.py` with minimal typed contracts:
   - intent extraction provider port
   - ticker search provider port
   - web search provider port
   - company profile provider port
2. Move external adapters to `infrastructure/*`:
   - split Yahoo/DDG/profile/LLM concerns into explicit provider owners.
3. Refactor `application/intent_service.py`:
   - remove direct infra imports and dotenv side effects.
   - keep orchestration and deterministic normalization only.
4. Refactor `application/factory.py` + add `intent/wiring.py`:
   - compose runtime providers in wiring.
   - inject typed ports into orchestrator.
5. Remove legacy `data/market_clients.py`.
6. Exit criteria:
   - no application->infrastructure direct imports (except wiring composition root).
   - no import-time side effects in application modules.

### Phase P2: Prompt ownership + runtime contract tightening
1. Move prompt specs from `domain/prompt_builder.py` to `interface/prompt_specs.py`.
2. Update prompt renderer and call sites to interface-owned prompt specs.
3. Tighten orchestrator boundary types:
   - reduce avoidable `object` usage in runtime dependencies.
4. Exit criteria:
   - domain no longer owns prompt strings.
   - orchestrator dependencies use typed runtime contracts.

### Phase P3: Compatibility cleanup + logging contract hardening
1. Remove clarification legacy fallback:
   - parser accepts canonical `selected_symbol` path only.
2. Keep interrupt payload contract deterministic and explicit.
3. Add start/completion/degraded structured logs on every terminal path:
   - extraction/searching/decision/clarifying.
4. Exit criteria:
   - no legacy resume key usage in implementation.
   - logging contract symmetric and machine-readable across terminal branches.

### Phase P4: Cleanup and verification closure
1. Remove obsolete compatibility helpers and unused imports.
2. Align tests for new contracts and owners.
3. Update blueprint status and residual risk notes.
4. Exit criteria:
   - no compatibility residue
   - all targeted checks pass.

## Risk/Dependency Assessment

Functional risks:
1. Clarification input contract change may break old frontend payload if any caller still sends `ticker`.
2. Provider failure contract change (typed degraded outcomes) may alter some degraded branches.

Runtime risks:
1. Adapter split may accidentally alter timeout/retry behavior if not carried over.

Migration risks:
1. Atomic move from `data` to `infrastructure` can break import paths if call-site migration is incomplete.

Mitigation:
1. Enforce per-phase exit criteria and run targeted tests after each phase.
2. Use one-step call-site migration per slice, then immediate legacy deletion.
3. Log degraded source/reason with stable error codes for quick rollback triage.

Rollback checkpoints:
1. End of P1 (before deleting compatibility artifacts permanently in branch history).
2. End of P3 (before final cleanup).

## Validation and Rollout Gates

Phase gates:
1. Static:
   - `ruff check` on touched intent + boundary files.
2. Unit/contract:
   - intent tests:
     - `test_intent_mapper.py`
     - `test_error_handling_intent.py`
     - `test_intent_interface_parsers.py`
     - `test_interrupts.py`
3. Architecture compliance:
   - no `application` direct infra imports (except wiring).
   - no prompt spec in `domain`.
   - no legacy `ticker` resume fallback.
4. Runtime/logging:
   - verify node start/completion/degraded logs are present and structured.

Final acceptance:
1. All phase gates pass.
2. Blueprint status updated to `In Progress` or `Completed` with implemented slice notes.

## Assumptions/Open Questions

Assumptions:
1. Frontend interrupt submit payload is already canonical (`selected_symbol`) or can be migrated together.
2. No requirement to keep backward-compatible `ticker` resume key.

Open questions:
1. Should we include `intent` import-hygiene guard test in this slice, or postpone to post-refactor hardening?
2. Do we want to migrate `intent` structured output invocation to async provider API in this round, or keep sync invocation as is for minimal behavioral risk?
