# Debate Clean Architecture Refactor Blueprint

Date: 2026-03-04
Scope: `finance-agent-core/src/agents/debate` (+ directly affected boundary module `src/workflow/nodes/debate/*`)
Status: Planned (ready for execution)
Policy baseline:
1. `finance-agent-core/docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
2. `finance-agent-core/docs/standards/refactor_lessons_and_cross_agent_playbook.md`
3. `finance-agent-core/docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
4. `finance-agent-core/docs/backlog/technical_analysis_clean_architecture_refactor_blueprint.md`
5. `finance-agent-core/docs/backlog/news_research_clean_architecture_refactor_blueprint.md`

Status update (2026-03-04):
1. D1-S1 (small, high-risk boundary rewiring) completed:
   - migrated debate external adapters from legacy `data/*` to canonical `infrastructure/*`:
     - `infrastructure/artifacts/debate_artifact_repository.py`
     - `infrastructure/artifacts/debate_source_reader_repository.py`
     - `infrastructure/market_data/capm_market_data_provider.py`
     - `infrastructure/sycophancy/sycophancy_detector_provider.py`
   - removed application-layer concrete composition from `application/factory.py`.
   - added composition root `src/agents/debate/wiring.py` with lazy accessor `get_debate_workflow_runner()`.
   - switched `workflow/nodes/debate/nodes.py` to wiring-owned runner access.
   - removed legacy `src/agents/debate/data/__init__.py` and deleted legacy `data` runtime files.
2. Validation (D1-S1):
   - `ruff check` passed on changed debate/workflow/tests paths.
   - targeted debate regression batch passed (`9 passed`).
3. Compliance gate (D1-S1):
   - no remaining `application -> debate.data|debate.infrastructure` direct concrete imports.
   - no remaining `src.agents.debate.data*` imports in source/tests.
4. Debug review remediation (D1-S1):
   - fixed legacy test collection residue:
     - `tests/test_debate_grounding.py`
     - `tests/test_debate_mapper.py`
   - import path migrated from removed `domain.report_contracts` to `domain.models`.
   - result: full debate-targeted regression suite passed (`33 passed`).
5. D2-S1 (small, contract correctness) completed:
   - implemented typed source-load degradation contract in debate artifact reader:
     - added `DebateSourceLoadIssue` in `application/dto.py`
     - `DebateSourceData` now carries `load_issues` and `is_degraded`
     - distinguished statuses: `missing_artifact_id`, `artifact_not_found`, `empty_payload`
   - propagated typed degraded observability into application flow:
     - `application/report_service.py` now returns `PreparedDebateReports`
     - added warning event `debate_reports_source_degraded` with machine-readable reason codes
     - `run_debate_aggregator` now emits `debate_aggregator_sources_degraded`, marks node status degraded, and writes warning `error_logs` when input sources degrade.
   - added tests for degraded visibility contract:
     - `tests/test_debate_optimization.py`
     - `tests/test_debate_report_reader.py`
6. Validation (D2-S1):
   - `ruff check` passed on changed debate/workflow/tests paths.
   - full debate-targeted regression suite passed (`34 passed`).
7. D3-S1 (small, async runtime safety) completed:
   - moved verdict pragmatic metrics computation off the event loop:
     - `application/orchestrator.py` now executes `calculate_pragmatic_verdict(...)` via `asyncio.to_thread(...)`.
   - result: sync market-data and numeric compute inside pragmatic verdict path no longer run directly on the async node loop.
8. Validation (D3-S1):
   - `ruff check` passed.
   - debate-targeted regression suite passed (`34 passed`).
9. D4-S1a (small, interface owner correction) completed:
   - moved debate preview projection owner from application to interface:
     - added `src/agents/debate/interface/preview_projection_service.py`
     - removed `src/agents/debate/application/view_models.py`
   - updated interface mapping owner:
     - `src/agents/debate/interface/mappers.py` now uses interface projection owner only.
   - updated preview layer tests:
     - `tests/test_debate_preview_layers.py`
10. Validation (D4-S1a):
    - `ruff check` passed on debate/workflow/tests paths.
    - debate-targeted regression suite passed (`34 passed`).
11. D4-S1b (small, prompt ownership correction) completed:
    - moved debate prompt templates from domain to interface:
      - added `src/agents/debate/interface/prompt_specs.py`
      - removed `src/agents/debate/domain/prompt_builder.py`
    - updated call sites:
      - `application/factory.py`
      - `application/orchestrator.py`
12. Validation (D4-S1b):
    - `ruff check` passed on debate/workflow/tests paths.
    - debate-targeted regression suite passed (`34 passed`).
13. D5-S1 (small, logging quality + bounded exception text) completed:
    - added start/completion summary logs for:
      - bull round
      - bear round
      - moderator round
    - completion logs now cover both success and degraded terminal paths for these node owners.
    - replaced raw exception text logging in debate runtime paths with bounded exception text utility:
      - `application/orchestrator.py`
      - `application/debate_llm_retry_service.py`
      - `infrastructure/market_data/capm_market_data_provider.py`
14. Validation (D5-S1):
    - `ruff check` passed on debate/workflow/tests paths.
    - debate-targeted regression suite passed (`34 passed`).
15. D6-S1 (small, semantic owner split) completed:
    - split generic `domain/services.py` into semantic owners:
      - `src/agents/debate/domain/pragmatic_verdict_policy.py`
      - `src/agents/debate/domain/report_compression_service.py`
    - migrated import call sites atomically:
      - `application/orchestrator.py`
      - `domain/fact_builders.py`
      - `interface/serializers.py`
      - `tests/test_technical_analysis.py`
    - removed legacy catch-all module:
      - `src/agents/debate/domain/services.py`
16. D6-S2 (small, runtime typing hardening) completed:
    - narrowed debate runtime typing on key boundaries:
      - `application/report_service.py` payload typed to `JSONObject`
      - `application/prompt_runtime.py` compression input typed to `JSONObject`
      - `application/orchestrator.py` verdict structured-output schema typed to `DebateConclusion`
      - `wiring.py` artifact output typed to `AgentOutputArtifactPayload | None`
    - fixed latent pragmatic verdict data-quality path safety:
      - ensured `rr_ratio` is always defined when `data_quality_warning=true` in
        `domain/pragmatic_verdict_policy.py`.
17. Validation (D6-S1/D6-S2):
    - `ruff check` passed on changed debate/workflow/tests paths.
    - debate+impacted regression batch passed:
      - `26 passed`, `3 warnings`.
18. Post-audit hardening tail completed:
    - offloaded synchronous sycophancy detector call from async moderator path:
      - `application/debate_service.py` now executes `detector.check_consensus(...)` via `asyncio.to_thread(...)`.
    - rationale: remove residual sync compute/inference work from event loop path and align fully with async boundary rule.
19. Validation (post-audit tail):
    - `ruff check` passed on changed debate/workflow/tests paths.
    - debate regression batch passed:
      - `21 passed`, `3 warnings`.

## Decision Log

1. Confirmed: debate source artifact `not_found` is allowed to continue in degraded mode, but must be explicit and observable in state/logs (must not be silently normalized as empty payload).
2. Migration mode: atomic clean migration without compatibility aliases/shims.

## Findings (Architecture Standard Enforcer)

Severity-ordered findings against canonical standard:

1. P1 - Layer boundary broken + non-canonical layer (`data/` acting as infrastructure).
   - `application` directly imports concrete adapters from `data`.
   - Wiring/composition ownership currently inside `application/factory.py`.
   - Violated rules: Layer boundaries (Rule 2), wiring outside use-case modules (Rule 5.1).
   - Refs:
     - `src/agents/debate/application/orchestrator.py:31`
     - `src/agents/debate/application/factory.py:10`
     - `src/agents/debate/application/factory.py:56`

2. P1 - Async event-loop path executes blocking sync network/heavy compute.
   - `run_verdict` calls sync market-data providers backed by yfinance/pandas/numpy in async flow.
   - Violated rules: async boundary (Rule 5.7), heavy compute path boundary (Rule 5.10).
   - Refs:
     - `src/agents/debate/application/orchestrator.py:506`
     - `src/agents/debate/data/market_data.py:58`
     - `src/agents/debate/data/market_data.py:228`
     - `src/agents/debate/data/market_data.py:292`

3. P1 - Artifact read semantics conflate `not_found` with `empty_payload`.
   - Missing IDs/data currently become `[]`/`None` without typed reason metadata.
   - Violated rules: artifact semantics (Rule 6.5), typed degraded outcomes (Rule 5.9).
   - Refs:
     - `src/agents/debate/data/report_reader.py:22`
     - `src/agents/debate/data/report_reader.py:28`
     - `src/agents/debate/data/report_reader.py:45`
     - `src/agents/debate/application/orchestrator.py:590`

4. P1 - Interface imports application owner + preview projection owner misplaced.
   - `interface/mappers.py` imports `application/view_models.py`.
   - Violated rules: interface must not import application (Rule 2.3), preview projection owner in interface (Rule 3.6).
   - Refs:
     - `src/agents/debate/interface/mappers.py:5`
     - `src/agents/debate/application/view_models.py:1`

5. P2 - Prompt ownership in domain.
   - Prompt templates live in `domain/prompt_builder.py`.
   - Violated rules: prompt specs/renderers in interface (Rule 3.5).
   - Refs:
     - `src/agents/debate/domain/prompt_builder.py:1`
     - `src/agents/debate/application/factory.py:17`
     - `src/agents/debate/application/orchestrator.py:585`

6. P2 - Naming/runtime boundary mismatch.
   - Concrete class named `*Port`.
   - Avoidable `object` types in application runtime boundaries.
   - Violated rules: suffix semantics (Rule 3.1), avoidable object in application runtime boundaries (Rule 5.3/5.5).
   - Refs:
     - `src/agents/debate/data/ports.py:17`
     - `src/agents/debate/application/orchestrator.py:63`
     - `src/agents/debate/application/orchestrator.py:86`

7. P2 - Logging quality contract incomplete.
   - Bull/Bear/Moderator lack start/completion summary symmetry.
   - Exception text logging uses raw `str(exc)` (unbounded).
   - Violated rules: logging start/completion symmetry (Rule 8.2), bounded exception text (Rule 8.7).
   - Refs:
     - `src/agents/debate/application/orchestrator.py:250`
     - `src/agents/debate/application/orchestrator.py:309`
     - `src/agents/debate/application/orchestrator.py:370`
     - `src/agents/debate/application/orchestrator.py:290`
     - `src/agents/debate/application/debate_llm_retry_service.py:123`

8. P3 - Generic catch-all mature modules reduce cohesion.
   - `domain/services.py`, `domain/models.py`.
   - Violated rules: avoid generic catch-all modules in mature contexts (Rule 3.3).
   - Refs:
     - `src/agents/debate/domain/services.py:1`
     - `src/agents/debate/domain/models.py:1`

## Requirement Breakdown

Objectives:
1. Converge debate agent to canonical cross-agent clean architecture.
2. Remove non-canonical layering and boundary leakage.
3. Keep no-compatibility refactor posture (no legacy shim retention).
4. Preserve behavior while improving maintainability/readability/robustness.

Constraints:
1. Do not over-design; abstractions must directly reduce complexity.
2. Prefer larger, atomic slices with deterministic validation gates.
3. Keep degraded behavior explicit and machine-readable.

Non-goals:
1. No change to debate strategy semantics unless required for boundary correctness.
2. No debate business-logic redesign beyond ownership split and runtime safety.

## Technical Objectives and Strategy

1. Structural convergence first: canonical package/layer ownership (`infrastructure` composition root + application ports).
2. Runtime correctness second: async-safe external compute/I/O boundaries.
3. State/contract correctness third: typed degraded outcomes and artifact read semantics.
4. Owner cleanup last: prompt/projection placement and generic-module semantic split.

## Involved Files

Primary (directly changed):
- `src/agents/debate/application/orchestrator.py`
- `src/agents/debate/application/factory.py`
- `src/agents/debate/application/ports.py`
- `src/agents/debate/application/debate_service.py`
- `src/agents/debate/application/report_service.py`
- `src/agents/debate/application/debate_llm_retry_service.py`
- `src/agents/debate/interface/mappers.py`
- `src/agents/debate/interface/formatters.py`
- `src/agents/debate/domain/prompt_builder.py` (move/remove)
- `src/agents/debate/domain/services.py` (split)
- `src/agents/debate/data/report_reader.py` (move/rename)
- `src/agents/debate/data/ports.py` (move/rename)
- `src/agents/debate/data/market_data.py` (move/rename)
- `src/agents/debate/data/sycophancy_client.py` (move/rename)

Boundary modules:
- `src/workflow/nodes/debate/nodes.py`

## Detailed Per-File Plan

### Phase D1 (P1): Layer + Wiring Convergence (Large)

Entry criteria:
- baseline tests green.

Actions:
1. Introduce canonical infrastructure route and move `data/*` owners into `infrastructure/*` with semantic names:
   - `infrastructure/artifacts/debate_artifact_repository.py`
   - `infrastructure/artifacts/debate_source_reader_repository.py`
   - `infrastructure/market_data/capm_market_data_provider.py`
   - `infrastructure/sycophancy/sycophancy_detector_provider.py`
2. Introduce `src/agents/debate/wiring.py` as composition root.
3. Remove concrete adapter imports from `application/orchestrator.py` and `application/factory.py`.
4. Keep node entrypoint (`workflow/nodes/debate/nodes.py`) wired via `get_debate_workflow_runner()` lazy accessor.

Exit criteria:
- no `application -> debate.data|debate.infrastructure` concrete imports.
- no import-time runner bootstrap side effects.

### Phase D2 (P1): Artifact Semantics + Typed Degraded Outcomes (Large)

Entry criteria:
- D1 completed.

Actions:
1. Add typed read outcome contracts in `application/ports.py` for source artifacts.
2. Replace silent `[]/None` normalization in repository/read boundary with explicit outcome states:
   - `not_found`
   - `empty_payload`
   - `ok`
3. Update `report_service.py`, `debate_service.py`, `orchestrator.py` to map outcomes to deterministic degraded state + reason logs.
4. Update `_load_valid_facts` path to preserve missing-vs-empty semantics.

Exit criteria:
- all artifact-read paths can distinguish missing vs empty.
- degraded reasons are machine-readable and propagated.

### Phase D3 (P1): Async Safety for Heavy Compute/Sync I/O (Large)

Entry criteria:
- D2 completed.

Actions:
1. Wrap sync market-data provider operations behind async boundary contract:
   - use `asyncio.to_thread(...)` (or executor abstraction) in infrastructure adapter.
2. Update verdict path to consume async-safe provider methods.
3. Add bounded concurrency guard if market fetch can be invoked concurrently.

Exit criteria:
- no sync market-data I/O/heavy compute runs directly on debate async node path.

### Phase D4 (P1/P2): Interface/Domain Ownership Convergence (Large)

Entry criteria:
- D3 completed.

Actions:
1. Move prompt template owner from domain to interface:
   - `interface/prompt_specs.py` (or `interface/prompt_renderers.py`).
2. Move preview projection owner from application to interface:
   - create `interface/preview_projection_service.py`
   - remove `application/view_models.py`.
3. Remove `interface -> application` import direction.

Exit criteria:
- no prompt templates under domain.
- no interface imports from application.

### Phase D5 (P2): Logging + Boundary Type Hardening (Medium)

Entry criteria:
- D4 completed.

Actions:
1. Add start/completion summary logs for bull/bear/moderator node paths.
2. Ensure completion logs emitted on all terminal paths (success/degraded/error).
3. Replace raw `str(exc)` logs with bounded exception text helper.
4. Reduce avoidable `object` types in application runtime protocols.

Exit criteria:
- debate nodes satisfy logging symmetry rule.
- exception logs bounded.

### Phase D6 (P3): Semantic Module Naming Cleanup (Medium)

Entry criteria:
- D5 completed.

Actions:
1. Split `domain/services.py` into semantic owners:
   - `domain/pragmatic_verdict_policy.py`
   - `domain/report_compression_service.py`
2. Keep `domain/models.py` if cohesive; otherwise split by bounded concept and remove generic naming.
3. Migrate imports atomically and delete legacy files.

Exit criteria:
- no generic catch-all module names remain in mature paths (where split increases clarity).

## Risk/Dependency Assessment

Functional risks:
1. Changing artifact read semantics can alter debate degradation frequency.
2. Async offload for market-data may change latency distribution and timeout behavior.

Migration risks:
1. Large package move (`data` -> `infrastructure`) can introduce import breakage if not atomic.
2. Prompt owner migration can break runtime if template paths are partially migrated.

Rollback strategy:
1. Keep phase-level checkpoints and run full validation per phase.
2. If a phase fails, rollback only that phase’s file set (no partial compatibility bridge retention).

## Validation and Rollout Gates

Per-phase mandatory checks:
1. `ruff check` for changed debate + workflow paths.
2. Targeted debate tests:
   - node/orchestrator flow tests
   - artifact semantics tests (`not_found` vs `empty_payload`)
   - logging contract tests (start/completion/degraded symmetry)
3. Runtime smoke:
   - full flow with debate enabled, verify output contract + degraded reason visibility.

Performance/runtime gate (D3 required):
1. Add minimal reproducible benchmark for verdict market-data subpath.
2. Enforce no regression threshold for async verdict completion latency.

## Assumptions/Open Questions

Resolved:
1. Debate source artifact `not_found` is degraded-continue, not hard fail; must be explicitly visible in state/logs.

Pending (default decision pre-set for execution unless overridden):
1. Execute as atomic large slices with no compatibility aliases (default: yes).

## Initial Execution Suggestion

Recommended order:
1. D1 + D2 as first combined large slice (boundary correctness first).
2. D3 as second large slice (runtime safety/perf).
3. D4 + D5 as third combined slice (owner and observability convergence).
4. D6 as final cleanup slice.

---

## D7 Enhancement Plan (Dual-Channel Grounding + Valuation Evidence)

Date: 2026-03-04
Status: Planned (ready for implementation)

Status update (2026-03-04):
1. D7-S1 completed (small, high-risk state contract slice):
   - removed legacy single-channel `compressed_reports` path.
   - introduced dual-channel internal state keys:
     - `context_summary_text`
     - `facts_registry_text`
   - updated debate prompt runtime assembly to inject explicit dual placeholders:
     - `{facts_registry}`
     - `{context_summary}`
2. D7-S2 completed (medium, valuation citeable evidence):
   - added valuation fact extraction from `fundamental_analysis.artifact.preview`.
   - extended debate evidence source contracts:
     - domain `SourceType` includes `valuation`
     - interface source-type parsing/literals include `valuation`
     - citation validator supports `V###` tags.
3. D7-S2b completed (medium, technical evidence depth):
   - expanded technical facts from single signal point to layered evidence:
     - signal + z-score
     - fracdiff optimal_d
     - memory strength
     - confluence states (bollinger/macd/obv) when present.
4. Validation (D7-S1/S2/S2b):
   - `ruff check` passed on changed debate/workflow/tests paths.
   - debate-targeted regression suite passed:
     - `34 passed`.
5. Compliance gate (D7-S1/S2/S2b):
   - no remaining reads/writes to legacy `compressed_reports`.
   - interface/domain/application boundaries unchanged and compliant for this slice.

### Requirement Breakdown

Objectives:
1. Replace single overwritten `compressed_reports` channel with dual-channel debate context:
   - `facts_registry_text` (strict citation registry)
   - `context_summary_text` (compressed multi-source narrative summary)
2. Make valuation outputs first-class citeable evidence in debate (not only implicit narrative context).
3. Keep no-compatibility posture: remove legacy single-channel state key once migrated.

Constraints:
1. Follow `docs/standards` boundaries and naming contracts.
2. Avoid over-design; prefer minimal additive contracts and deterministic migration.
3. Keep citation/audit flow deterministic and machine-checkable.

Non-goals:
1. No redesign of bull/bear/moderator strategy semantics.
2. No new microservice split or cross-process architecture changes.

### Technical Objectives and Strategy

1. Separate context channels by owner and purpose:
   - facts registry for citation enforcement
   - summary context for qualitative synthesis
2. Keep all three debate input artifacts explicit and typed in source-reader boundary:
   - Fundamental: `ARTIFACT_KIND_FINANCIAL_REPORTS`
   - News: `ARTIFACT_KIND_NEWS_ANALYSIS_REPORT`
   - Technical: `ARTIFACT_KIND_TA_FULL_REPORT`
3. Add valuation evidence extraction from canonical fundamental context (`fundamental_analysis.artifact.preview`) in application/domain layer.
4. Extend evidence contract once (typed + parser + validator) to support valuation evidence IDs.
5. Migrate prompt spec placeholders to explicit two-channel injection and remove single `{reports}` dependency.

### Involved Files

Primary:
1. `src/agents/debate/application/orchestrator.py`
2. `src/agents/debate/application/debate_service.py`
3. `src/agents/debate/application/debate_context.py`
4. `src/agents/debate/application/report_service.py`
5. `src/agents/debate/application/dto.py`
6. `src/agents/debate/infrastructure/artifacts/debate_source_reader_repository.py`
7. `src/agents/debate/domain/fact_builders.py`
8. `src/agents/debate/domain/models.py`
9. `src/agents/debate/domain/validators.py`
10. `src/agents/debate/interface/prompt_specs.py`
11. `src/agents/debate/interface/types.py`
12. `src/agents/debate/interface/contracts.py`
13. `src/agents/debate/interface/serializers.py`

Directly affected artifact contracts:
1. `src/agents/technical/interface/contracts.py` (if TA artifact parsing is tightened to model parse path)

Boundary/state:
1. `src/workflow/nodes/debate/subgraph_state.py`
2. `src/workflow/state.py` (only if new cross-node field is persisted; otherwise keep changes local to subgraph state)

Tests:
1. `finance-agent-core/tests/test_debate_*` (prompt/runtime/facts/validators/orchestrator targets)

### Detailed Per-File Plan

#### D7-S1 (Large): Dual-Channel Context Contract

Actions:
1. Introduce two explicit internal state keys in debate subgraph:
   - `facts_registry_text`
   - `context_summary_text`
2. Update `run_debate_aggregator` to write only `context_summary_text`.
3. Update `run_fact_extractor` to write only `facts_registry_text` (no overwrite of summary channel).
4. Update debate context reader and report service cache logic to consume the new keys and remove legacy `compressed_reports` route.
5. Update bull/bear/moderator prompt assembly to inject both channels explicitly.

Exit criteria:
1. No write/read of legacy `compressed_reports`.
2. Logs clearly indicate channel source (`cached/computed`) per channel.

#### D7-S2 (Large): Valuation Evidence as Citeable Facts

Actions:
1. Add valuation fact extraction from canonical fundamental valuation preview (intrinsic value, upside/downside signal, distribution anchors, key diagnostics when present).
2. Extend evidence typing/contracts to include valuation source:
   - source type map and literals
   - citation ID family extension (e.g., `V###`)
3. Extend citation validator regex/compliance parsing to accept valuation fact IDs while preserving existing bull financial-citation minimum rule.
4. Include valuation evidence in strict registry rendering and facts summary counts.
5. Optionally include compact valuation block in narrative summary payload (if present) without duplicating full payload in state.

Exit criteria:
1. Debate transcript can cite valuation evidence IDs and pass validator.
2. Facts artifact schema and parser accept valuation source type deterministically.

#### D7-S2b (Large): Technical Evidence Depth + Artifact Parse Hardening

Actions:
1. Tighten technical artifact parsing in debate source reader to typed model boundary (instead of loose JSON-only parse), while keeping degraded handling semantics unchanged.
2. Expand technical fact extraction beyond single signal fact:
   - directional signal + z-score
   - memory/fracdiff metrics (where present)
   - confluence components (bollinger/macd/obv) as separate citeable facts when available
3. Keep technical facts concise; avoid over-fragmentation and keep deterministic IDs/order.

Exit criteria:
1. Technical artifact read path is typed and contract-safe.
2. Debate gets richer T-facts without changing technical agent output contract semantics.

#### D7-S3 (Medium): Prompt/Observability Hardening

Actions:
1. Update prompt specs to show separate sections:
   - `FACTS_REGISTRY (STRICT CITATION REQUIRED)`
   - `CONTEXT SUMMARY (NON-CITABLE BACKGROUND)`
2. Add structured logs for channel availability and size:
   - `facts_registry_chars/hash`
   - `context_summary_chars/hash`
3. Keep degraded path machine-readable when either channel is unavailable.

Exit criteria:
1. Start/completion/degraded logs remain symmetric and bounded.
2. Prompt input shape is stable and explicit.

### Risk/Dependency Assessment

Functional risks:
1. Validator/prompt updates may temporarily reduce citation pass rate if ID patterns are partially migrated.
2. Valuation preview fields are optional across models; extraction must remain tolerant and avoid false hard-fail.

Migration risks:
1. Single-key to dual-key migration can break rounds if one read path is missed.
2. Contract changes (`source_type`, fact ID pattern) can break artifact parsing/tests if not updated atomically.

Mitigation:
1. Implement S1/S2 atomically in one branch with immediate test coverage updates.
2. Keep fallback behavior explicit: missing valuation preview -> no valuation facts, not fatal.

### Validation and Rollout Gates

Mandatory:
1. `ruff check` on changed debate/workflow/interface files.
2. Debate-targeted pytest batch covering:
   - dual-channel cache behavior (no overwrite)
   - valuation fact generation and citation validation
   - prompt renderer input contract
   - orchestrator path (aggregator + fact extractor + one round)
3. Runtime smoke with one full debate execution:
   - verify both channels logged and present
   - verify valuation evidence count in facts summary
   - verify no legacy `compressed_reports` key writes

### Assumptions/Open Questions

Assumptions:
1. Canonical valuation context remains `fundamental_analysis.artifact.preview`.
2. Valuation evidence IDs will use a dedicated prefix (recommended: `V###`) for readability and auditability.

Open questions (default decision pre-set):
1. Whether valuation facts should count toward Bull’s “>=3 financial citations” requirement.
   - Default: no, keep the financial (`F###`) minimum unchanged for discipline.
