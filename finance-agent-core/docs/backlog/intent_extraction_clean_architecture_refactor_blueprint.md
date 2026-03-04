# Intent Extraction Clean Architecture Refactor Blueprint

Date: 2026-03-04
Scope: `finance-agent-core/src/agents/intent`
Status: Completed
Policy baseline:
1. `finance-agent-core/docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
2. `finance-agent-core/docs/standards/refactor_lessons_and_cross_agent_playbook.md`

Status update (2026-03-04):
1. I-01 (P0 baseline, small) completed:
   - fixed stale test import residue from removed legacy module:
     - `tests/test_intent_mapper.py`: `src.agents.intent.domain.report_contracts` -> `src.agents.intent.domain.models`
   - verification:
     - `ruff check` passed for changed test file
     - targeted intent tests passed (`16 passed`)
     - residue scan confirms no remaining `src.agents.intent.domain.report_contracts` references.
2. I-02 (P3 compatibility cleanup, small) completed:
   - removed legacy `ticker` fallback from clarification resume flow:
     - `application/orchestrator.py`: `resolve_selected_symbol` now accepts canonical `selected_symbol` only
     - `interface/parsers.py`: `ResolvedSelectionInput` now exposes only `selected_symbol`
   - updated parser tests to canonical contract behavior.
   - verification:
     - `ruff check` passed on changed intent files
     - targeted tests passed (`16 passed`)
   - compliance note:
     - this slice resolves a blocking migration-hygiene violation (legacy compatibility residue) and introduces no new hard-rule violations.
3. I-03 (P1 layer ownership convergence, small) completed:
   - moved intent external adapters from legacy `data/` route to `infrastructure/` owners:
     - `infrastructure/market_data/company_profile_provider.py`
     - `infrastructure/market_data/yahoo_ticker_search_provider.py`
     - `infrastructure/search/ddg_web_search_provider.py`
   - updated composition import route in `application/factory.py`
   - removed legacy files:
     - `data/market_clients.py`
     - `data/__init__.py`
   - synced directly impacted reference doc path:
     - `workflow/nodes/fundamental_analysis/README.md`
4. I-04 (P1 layer rewiring bootstrap, small) completed:
   - moved runtime composition ownership out of application:
     - added `src/agents/intent/wiring.py`
     - `workflow/nodes/intent_extraction/nodes.py` now pulls orchestrator via wiring
   - removed import-time env side effect from application:
     - removed `load_dotenv/find_dotenv` from `application/intent_service.py`
   - removed direct application->infrastructure imports for LLM:
     - `intent_service` now receives `llm_provider_fn` by injection.
   - verification:
     - `ruff check` passed
     - targeted intent/protocol tests passed (`27 passed`)
   - compliance note:
     - changed paths no longer show application direct imports from `intent.infrastructure` or global `src.infrastructure.llm`.
5. Next slice:
   - I-05 (small): introduce explicit `application/ports.py` runtime contracts and switch `application/factory.py` to typed port injection (reduce callable-bundle coupling).
6. I-05 (P2 prompt ownership convergence, small) completed:
   - moved intent prompt specs from domain to interface:
     - added `interface/prompt_specs.py`
     - removed `domain/prompt_builder.py`
     - updated `application/intent_service.py` imports to interface owner
   - cleaned stale domain export in `domain/__init__.py`.
   - verification:
     - `ruff check` passed
     - targeted intent/protocol tests passed (`27 passed`)
   - compliance note:
     - changed paths no longer contain prompt specs under `domain`.
7. I-06 (P2 runtime contract convergence, small) completed:
   - added explicit runtime contracts in `application/ports.py`:
     - `IIntentLlmProvider`
     - `IIntentTickerSearchProvider`
     - `IIntentWebSearchProvider`
     - `IIntentCompanyProfileProvider`
     - `IntentRuntimePorts`
   - migrated `application/factory.py` to inject a single typed `runtime_ports` bundle (instead of scattered runtime callables in factory signature).
   - updated `wiring.py` composition to build and inject `IntentRuntimePorts`.
   - verification:
     - `ruff check` passed
     - targeted intent/protocol tests passed (`27 passed`)
   - compliance note:
     - application composition boundary now depends on explicit runtime contract owner (`application/ports.py`) and keeps concrete adapter imports in wiring.
8. Next slice:
   - I-07 (small): strengthen provider degraded semantics (remove bare `None` for profile fetch failures) with typed failure metadata and align orchestrator handling/logging.
9. I-07 (P1/P2 degraded semantics hardening, small) completed:
   - introduced typed company profile lookup outcome in `application/ports.py`:
     - `IntentCompanyProfileLookup(profile, failure_code, failure_reason)`
   - updated provider contract and implementation:
     - `infrastructure/market_data/company_profile_provider.py`
     - now distinguishes:
       - `INTENT_PROFILE_NOT_FOUND`
       - `INTENT_PROFILE_PROVIDER_ERROR`
     - no bare `None` failure return path.
   - aligned orchestrator handling/logging:
     - `application/orchestrator.py` now consumes typed profile lookup result
     - warning logs include provider-level failure code/reason on profile lookup failure.
   - verification:
     - `ruff check` passed
     - targeted tests passed (`30 passed`)
     - added deterministic provider tests:
       - `tests/test_intent_company_profile_provider.py`
   - compliance note:
     - changed paths now satisfy typed degraded-outcome requirement for company-profile provider.
10. Next slice:
   - I-08 (small): normalize intent node completion logging so extraction/searching/decision each emits terminal completion summary on all return paths.
11. I-08 (P3 logging contract hardening, small) completed:
   - normalized terminal completion summary logs for:
     - `run_extraction`
     - `run_searching`
     - `run_decision`
   - each terminal return path now emits a stable completion event with machine-readable fields:
     - `status`
     - `goto_node`
     - `is_degraded`
     - scope metrics (`candidate_count`, `resolved_ticker`, etc. where applicable)
   - added explicit `intent_decision_started` log to align start/completion symmetry for decision node.
   - verification:
     - `ruff check` passed on changed files
     - targeted intent tests passed (`24 passed`)
   - compliance note:
     - changed intent node paths now satisfy logging completion symmetry requirement for extraction/searching/decision.
12. Next slice:
   - I-09 (small): extend completion-summary symmetry to clarification node terminal paths (`clarification_node` success + retry branches) for full P3 closure.
13. I-09 (P3 logging contract closure, small) completed:
   - extended clarification node completion-summary symmetry in:
     - `src/workflow/nodes/intent_extraction/nodes.py`
   - `clarification_node` now emits `intent_clarification_completed` on both terminal branches:
     - resolved branch (`goto=END`)
     - retry branch (`goto=extraction`)
   - completion event fields include machine-readable quality/context:
     - `status`
     - `goto_node`
     - `is_degraded`
     - `candidate_count`
     - `resolved_ticker`
   - verification:
     - `ruff check` passed on changed file
     - targeted intent tests passed (`24 passed`)
   - compliance note:
     - intent extraction/searching/decision/clarification now all satisfy start+completion symmetry for terminal branches per logging quality rules.
14. Next slice:
   - I-10 (small): P4 cleanup/closure pass (remove any leftover stale comments/imports, run full intent targeted verification, and finalize blueprint completion status).
15. I-10 (P4 cleanup/closure, small) completed:
   - performed cleanup/residue scan for intent scope:
     - no remaining direct `application -> infrastructure` imports in intent application layer
     - no prompt spec ownership leakage back to `domain`
     - no legacy clarification resume fallback (`selected_symbol` canonical path intact)
   - executed full intent-targeted closure gates:
     - `ruff check` on intent package + intent workflow node + intent-related test files
     - expanded pytest suite for intent + interrupt/protocol/subgraph/state-contract boundaries
   - verification:
     - `ruff check` passed
     - `pytest` passed (`35 passed`)
   - compliance note:
     - no blocking architecture-standard violations found in changed intent paths.
16. Next slice:
   - None. Intent extraction refactor slices I-01..I-10 are completed.
17. Post-completion hardening (small) completed:
   - fixed runtime boundary ergonomics in orchestrator construction:
     - removed long flat callable-bundle injection from `IntentOrchestrator`
     - orchestrator now depends on `IntentRuntimePorts` as the single runtime boundary owner
   - fixed bounded exception logging in intent scope:
     - added shared helper `bounded_text(...)` in `src/shared/kernel/tools/logger.py`
     - replaced raw `str(exc)` logging/failure text in intent application + infrastructure modules
   - verification:
     - `ruff check` passed on changed intent/shared files
     - intent closure test suite passed (`35 passed`)
   - compliance note:
     - no remaining long `*_fn: Callable[...]` injection fields in intent orchestrator
     - no remaining raw `str(exc)` in intent scope logs.
18. Post-log-review hardening (small) completed:
   - fixed search-channel degraded observability:
     - introduced typed web-search runtime outcome in `application/ports.py` (`IntentWebSearchResult`)
     - `intent_search_completed` now reflects `is_degraded=true` when web channel fails/empty and Yahoo fallback is used
     - added dedicated degraded reason event: `intent_search_degraded_web_channel`
   - adjusted web-search severity semantics:
     - "no results found" now logs as warning (`INTENT_WEB_SEARCH_EMPTY`) instead of error
   - fixed extraction completion field semantics:
     - `intent_extraction_completed.fields.resolved_ticker` now emits `null` for empty ticker instead of empty string
   - verification:
     - `ruff check` passed on changed files
     - intent closure test suite passed (`37 passed`)
     - added regression tests in `tests/test_error_handling_intent.py` for degraded completion signal + null ticker field semantics
19. Governance follow-up completed:
   - ran skill governance triage and classified update owner as `agent-debug-review-playbook`
   - applied minimal reusable playbook improvement for multi-source degraded-observability review checks
   - `quick_validate.py` passed for updated skill.

## Requirement Breakdown

Objectives:
1. Review and refactor `intent` to strict clean architecture alignment.
2. Detect and remove leftovers from the historical split (`intent` previously coupled with `fundamental` era).
3. Keep maintainability/readability/robustness as first priority, without over-design.
4. Do not keep long-lived compatibility paths.

Constraints:
1. Execution follows controlled `small|medium` slices with immediate validation and compliance gates.
2. Refactor should prefer larger, atomic slices.
3. Directly impacted boundary modules may be included (`workflow/nodes/intent_extraction/*`, `workflow/state.py`, `tests/*intent*`).

Non-goals:
1. No functional strategy changes to intent business semantics unless required by architecture correctness.
2. No refactor of `debate` in this slice.

## Initial Findings (Baseline)

Note: this section records pre-refactor baseline findings from planning time. Resolution status is tracked in the `Status update` slices above.

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
