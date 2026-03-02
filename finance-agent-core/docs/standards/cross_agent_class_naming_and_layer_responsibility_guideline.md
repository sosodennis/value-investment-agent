# Cross-Agent Class Naming and Layer Responsibility Guideline

Date: 2026-02-27
Scope: `finance-agent-core/src/agents/*`
Status: Draft for review
Policy: clean boundaries, explicit naming, no compatibility-driven ambiguity.

## 1. Purpose

This guideline extracts a reusable cross-agent standard from the current fundamental refactor review, so new and existing agents follow one naming and ownership model.

Primary goals:

1. Make class/file names self-explanatory.
2. Prevent mixed responsibilities across layers.
3. Reduce drift between `fundamental/news/debate/technical/intent`.
4. Provide a consistent baseline for upcoming refactors.

## 2. Canonical Layer Model

Target layering:

1. `domain`: business rules, invariants, deterministic logic.
2. `application`: use-case orchestration and process coordination.
3. `interface`: contracts/parsers/serializers/mappers for boundaries.
4. `infrastructure`: external integrations, persistence adapters, runtime config.

Current compatibility note:

1. Existing `data/` packages are treated as legacy infrastructure adapters.
2. New code should prefer `infrastructure/` naming and split.
3. During migration, keep ports in application and concrete adapters out of domain/application.

## 3. Layer Responsibilities and Boundaries

### 3.1 Domain

Responsibilities:

1. Domain entities, value objects, rules, policies, deterministic calculators.
2. Validation and invariants tied to financial/business meaning.

Boundaries:

1. No network, DB, filesystem, env reads, or framework wiring.
2. No artifact envelope or API transport formatting.

### 3.2 Application

Responsibilities:

1. Use-case flow (`run_*`, `*_orchestrator`, coordination services).
2. Calls domain + ports.
3. Composes domain results for interface serialization.

Boundaries:

1. No direct concrete provider/client imports.
2. No low-level transport concerns.
3. No business math duplicated from domain.

### 3.3 Interface

Responsibilities:

1. Boundary contracts (Pydantic models, typed payloads).
2. Parse/serialize/map between transport and application/domain shapes.
3. User-facing formatting/prompt rendering.

Boundaries:

1. No persistence or external API calls.
2. No domain decision policy.

### 3.4 Infrastructure (Priority Focus)

Responsibilities:

1. External provider integration (SEC, Yahoo, FRED, search, model APIs).
2. Artifact repositories and storage gateways.
3. Runtime config loading and infra policy.
4. Source-specific transformation to canonical models.

Boundaries:

1. No orchestration of workflow state machine.
2. No domain policy decisions disguised as adapters.
3. No import-time side effects (registration, identity setup, env mutation).

## 4. Cross-Agent Naming Standard

## 4.1 File Naming

1. `snake_case.py`, noun-first and role-explicit.
2. Main file role must match main class role:
   - `*_service.py` -> `*Service`
   - `*_provider.py` -> `*Provider`
   - `*_repository.py` -> `*Repository`
   - `*_client.py` -> `*Client`
   - `*_factory.py` -> `*Factory`
   - `*_mapper.py` -> `*Mapper`
   - `*_policy.py` -> `*Policy`
3. Avoid generic files like `tools.py`, `rules.py`, `helpers.py`, `structures.py` for new modules.
4. Runtime source packages should not use placeholder-style names like `_template`; prefer semantic owners such as `base_*`, `shared`, or `policies`.
5. For domain model input/output contracts, use `contracts.py` as canonical module name; avoid mixed `schemas.py` naming in the same package family.

## 4.2 Class Suffix Semantics (Mandatory)

1. `*Provider`: single upstream source adapter only.
2. `*Service`: multi-step coordination or use-case flow.
3. `*Repository`: persistence read/write gateway.
4. `*Client`: low-level transport/SDK wrapper.
5. `*Factory`: object assembly only, no orchestration.
6. `*Mapper`: shape transformation only, no business policy.
7. `*Policy`: threshold/rule/config policy, no I/O workflow.
8. `*Port`: abstract protocol/interface only, never concrete.

## 4.3 Infrastructure Naming Rules (Mandatory)

1. Do not name concrete classes as `*Port`.
2. Separate source adapter and aggregator roles:
   - source adapters: `*Provider`
   - cross-source aggregation/fallback/cache: `*Service`
3. If both `Client` and `Provider` exist:
   - `Client` handles raw transport
   - `Provider` converts raw data to canonical model
4. Repository names must encode storage intent:
   - good: `FundamentalArtifactRepository`
   - avoid: `FundamentalArtifactPort` (when concrete)
5. Factory classes should be small and composable; oversized "god factory" must split by responsibility.
6. Avoid one-hop compatibility alias modules that only re-export the same symbol:
   - avoid: `financial_payload_provider.py` -> `provider.fetch_financial_payload`
   - use one canonical owner module and migrate call sites directly.
7. Canonical contract fields must store canonical tokens, not source-specific labels:
   - avoid: `industry_type="Financial Services"` or `extension_type="Financial"` in canonical payload
   - use: `industry_type="FinancialServices"` and `extension_type="FinancialServices"`; keep source labels inside adapter routing only.
8. Interface validators/parsers must reject non-canonical labels for canonical fields:
   - do not silently normalize `industry_type="Financial Services"` or `extension_type="Financial"` in interface contract parsing.
9. Source-label alias normalization helpers belong to boundary layers only:
   - keep alias normalization in infrastructure/interface adapters, not domain shared modules.
10. Keep entrypoint modules thin:
   - model registry/cache wiring (e.g., `lru_cache` registries and dependency assembly) should live in dedicated `*_service.py` modules, not mixed inside entrypoint orchestrators.
11. Do not drive control-flow decisions from human-readable assumption/log strings:
   - avoid deriving runtime decisions from `assumptions` text fragments (e.g., `"sourced from market data" in assumptions`)
   - use typed flags/fields in owner service outputs instead.
12. Application orchestrators should be thin delegators:
   - keep `run_*` workflow branches in `application/use_cases/*`
   - orchestrators should only hold runtime capabilities/dependencies and delegate execution.
13. Large mapping registry catalogs must be split by semantic owner modules:
   - for source mapping registries (for example XBRL base mappings), keep `base.py`/entrypoint module as thin registration orchestrator
   - move mapping definitions into dedicated modules by capability (for example core/debt/income/cash-flow).
14. When decomposing widely-used owner modules, preserve stable utility entrypoints or migrate all call sites atomically:
   - if utility methods/symbols are consumed across modules (for example resolver ranking helpers), keep thin compatibility wrappers in the owner entrypoint during the same refactor batch
   - remove wrappers only after call-site migration and regression verification.
15. Fallback/retry branches must reuse the same extraction owner flow:
   - avoid copy-pasting strict vs relaxed extraction blocks inside one builder module
   - keep one extraction service and switch behavior via explicit config transformation (for example relaxed statement filters).
16. Do not keep mixed-policy monolith modules in domain:
   - avoid one file mixing growth blend policy, manual default policy, and forward-signal policy
   - split by policy capability under `domain/.../policies/*_policy.py`, and migrate call sites atomically rather than adding long-lived compatibility facades.
17. For stateful model-inference filters, keep lifecycle/cache in a thin orchestrator and move pure steps to dedicated services:
   - orchestrator owner keeps only load/warmup/cache/concurrency control
   - prefilter, inference batching/cache-key resolution, and stats shaping belong to separate `*_service.py` or `*_stats.py` modules.
18. For large deterministic engines, separate contracts from runtime services:
   - keep dataclass/config/result contracts in a dedicated `*_contracts.py`
   - keep engine entrypoint focused on orchestration and delegate sampling/math/diagnostics to dedicated owner services.
19. For financial statement extraction builders, split XBRL catalog, extraction, and derived-metric logic:
   - `*_config_service.py` owns concept/config bundles
   - `*_component_extraction_service.py` owns source field extraction and direct computed fields
   - `*_derived_metrics_service.py` owns ratio/derived policy math
   - builder entrypoint stays orchestration-only.
20. For text-signal processing pipelines, separate per-record preparation from per-metric accumulation:
   - record preparation service owns focus/8-K refinement/FLS routing and document metadata assembly
   - metric service owns regex/lemma/dependency hit aggregation and evidence merge policy
   - pipeline entrypoint keeps batch orchestration and diagnostics aggregation only.
21. For policy modules that ingest external payloads, separate parsing from scoring decisions:
   - parser service owns schema filtering and payload normalization into typed contracts
   - scoring service owns weighting/rejection/risk-tag policy decisions
   - policy entrypoint module keeps public exports and thin orchestration only.
22. For application `run_*` use-cases, separate context loading from execution and completion shaping:
   - context service owns state/artifact/runtime resolution and validation
   - execution service owns parameter build + deterministic calculation invocation
   - completion-fields service owns logging/telemetry field shaping
   - `run_*` entrypoint keeps node control flow and update routing only.
23. Do not introduce catch-all helper modules as mixed responsibility sinks:
   - avoid modules like `pipeline_helpers.py` that mix scalar conversion, text normalization, filing access, URL construction, snippet extraction, and evidence dedupe
   - split by capability owner modules and let call sites import those owners directly.
24. For domain model-selection engines, separate capability owners:
   - contracts/types and scoring weights in `*_contracts.py`
   - model catalog/spec registry in `*_spec_catalog.py`
   - signal extraction in `*_signal_service.py`
   - scoring policy in `*_scoring_service.py`
   - reasoning text assembly in `*_reasoning_service.py`
   - keep `model_selection.py` as thin orchestration entrypoint only.
25. For domain valuation backtest runners, separate capability owners:
   - contracts in `backtest_contracts.py`
   - dataset/baseline I/O and coercion in `backtest_io_service.py`
   - runtime case execution in `backtest_runtime_service.py`
   - drift comparison in `backtest_drift_service.py`
   - report/baseline payload shaping in `backtest_report_service.py`
   - keep `backtest.py` as thin API entrypoint only.
26. For shared DCF variant calculators, separate validation, stochastic distribution, and result assembly owners:
   - keep protocols/policies in `dcf_variant_contracts.py`
   - projection validation/coercion in `dcf_variant_validation_service.py`
   - Monte Carlo distribution and batch evaluator in `dcf_variant_distribution_service.py`
   - output/detail assembly in `dcf_variant_result_service.py`
   - keep `dcf_variant_calculator.py` as thin orchestration entrypoint only.
27. Do not keep implementation residue through generic utility buckets or class static wrappers:
   - avoid keeping runtime integration logic in `utils.py` after capability owners are identified
   - migrate to semantic `*_service.py` modules and remove the legacy utility module
   - do not expose cross-module utility functions through class static wrappers when a direct service function dependency is sufficient.
28. Do not split one bounded capability across root-prefixed modules and a sibling package with overlapping ownership:
   - avoid structures like `x_builder*.py` at `domain/.../` plus `x_builders/*` in parallel
   - converge to one canonical capability package (for example `.../parameterization/*`) and keep entrypoint/orchestration/shared/model-specific owners inside that package.
29. Inside a canonical capability package, avoid module-name stutter that repeats the package capability token:
   - avoid `parameterization/param_builder_contracts.py` and `parameterization/param_builder_orchestrator.py`
   - use semantic owner module names like `contracts.py`, `orchestrator.py`, `registry_service.py`, `policy_service.py`.
30. For dense model-builder families, avoid flat file saturation in one package:
   - split model-specific owners into per-model subpackages (for example `model_builders/bank/*`, `model_builders/saas/*`)
   - keep cross-model reusable owners under a dedicated shared subpackage (for example `model_builders/shared/*`)
   - keep dispatcher/context modules at the parent package boundary.
31. In policy-oriented capability packages, avoid mixing independent policy capabilities in one module:
   - avoid single modules that combine forward-signal adjustment flow with data-freshness/time-alignment guard logic
   - keep capability owners separated (for example parser/adjustment/time-guard services)
   - keep `policy_service.py` as thin entrypoint/re-export only.
32. Keep concrete dependency wiring outside application modules:
   - application modules must depend on ports/contracts only
   - concrete repository/provider/service assembly and singleton runtime wiring belong to dedicated composition/wiring modules.
33. Avoid import-time registry bootstrap in infrastructure catalogs:
   - do not execute mapping/rule registration during module import
   - expose explicit or cached accessor functions (for example `get_*_registry()`) and perform registration lazily at runtime.
34. Avoid generic domain-root modules (`models.py`, `services.py`, `rules.py`) in matured bounded contexts:
   - keep only semantic owner modules (for example `valuation_model.py`, `financial_health_service.py`, `valuation_output_service.py`)
   - if multiple capabilities exist, split by capability owner and migrate call sites atomically.
35. Promote mature multi-module capabilities into dedicated subpackages:
   - when one capability grows to 4+ tightly-coupled owner modules under a parent package (for example `backtest_*` in `domain/valuation`), group them under `domain/.../<capability>/`
   - keep only one thin public entrypoint at parent level when needed for API stability; avoid long-term flat `capability_*` module clusters.

## 4.4 Acronym and Case Rules

1. Use `PascalCase` for class names.
2. Acronyms follow one style across project:
   - preferred: acronym as normal word (`Sec`, `Xbrl`, `Finbert`, `Fred`)
3. Do not mix styles in same module family:
   - avoid: `SECFetchPolicy` with `_SecRateLimiter`
   - choose one style and keep consistent.

## 5. Dependency Rules (Hard Constraints)

1. `domain` can depend on `domain` + shared kernel only.
2. `application` can depend on `domain` + application ports/contracts, not concrete infrastructure.
3. `interface` can depend on application/domain public types only.
4. `infrastructure` can depend on ports and shared types; reverse dependency is forbidden.
5. Workflow/subgraph nodes stay orchestration-only and call application entrypoints.

## 6. Package Shape Recommendation (Per Agent)

```text
src/agents/<agent>/
  domain/
  application/
    ports/
    services/
    use_cases/
  interface/
  infrastructure/        # target end-state
  data/                  # legacy transitional adapter package
```

Rules:

1. Avoid duplicated directory segments like `application/fundamental`.
2. Use capability-oriented packages, not historical labels.
3. For migration windows, keep legacy `data` as shim and retire progressively.
4. Avoid stuttering package/module prefixes inside an already-scoped context:
   - avoid: `domain/valuation/models/valuation_dcf_standard`
   - use: `domain/valuation/models/dcf_standard`
5. Place cross-model domain policies under dedicated `domain/.../policies` packages:
   - avoid: `domain/valuation/models/audit_policies/...`
   - use: `domain/valuation/policies/...`
6. Do not keep prompt/agent-spec artifacts (for example `SKILL.md`) inside runtime source packages.
7. For model families with shared deterministic formulas (for example DCF variants), keep shared logic in `domain/.../calculators/*_calculator.py` and keep model-local calculators as thin variant wrappers.
8. Repeated calculator runtime support (for example trace-input merge, traceable unwrap, upside computation) must live in one shared owner module under `domain/.../calculators`, not duplicated per model package.
9. For matured valuation domains, `domain/.../models` should keep contracts only; runtime calculators must be imported from `domain/.../calculators` by registries and call sites.
10. For matured capability families, keep all implementation owners inside a single package boundary instead of split roots + sibling packages:
   - avoid: `domain/valuation/x_builder*.py` + `domain/valuation/x_builders/*`
   - use: `domain/valuation/x/*` (or semantic equivalent like `domain/valuation/parameterization/*`).
11. Once a capability package is canonicalized, remove inner module stutter:
   - avoid repeating the capability token in every filename inside that package
   - keep filenames capability-neutral and owner-semantic (`contracts.py`, `types.py`, `orchestrator.py`, `*_service.py`).
12. For builder-heavy capability packages, prefer two-level shape:
   - parent package for orchestration/wiring/context
   - child subpackages for model-specific builders plus one `shared` subpackage for reusable extraction/output/policy helpers.
13. For matured domain capabilities with multiple owner modules (for example backtest contracts/io/runtime/drift/report), prefer subpackage grouping:
   - use `domain/.../<capability>/contracts.py`, `.../io_service.py`, `.../runtime_service.py`, `.../report_service.py`
   - avoid keeping long-lived flat siblings like `<capability>_contracts.py`, `<capability>_io_service.py`, `<capability>_runtime_service.py` at the parent package root.

## 7. Common Naming Anti-Patterns

1. Concrete implementation named as `*Port`.
2. Generic filenames like `tools.py` / `rules.py` / `models.py` / `services.py` hiding mixed concerns.
3. One class mixing `Provider + Policy + Orchestrator`.
4. Import-time global registration/setup.
5. Same concept split into multiple names (`Payload`, `Model`, `Contract`) without boundary definition.

## 8. Minimal Review Checklist (For PRs)

1. Is class suffix aligned with real responsibility?
2. Is file name aligned with main class?
3. Is any concrete class still named `*Port`?
4. Is any infrastructure class making domain decisions?
5. Any import-time side effects introduced?
6. Any duplicated acronym style in same package?
7. Any large factory/service that should be split?
8. Any control decision derived from narrative assumption/log strings instead of typed fields?
9. Any stateful inference module still mixing lifecycle/cache with prefilter/batching/scoring logic in one file?
10. Any large deterministic engine still mixing contracts, runtime orchestration, and low-level math/sampling in one file?
11. Any statement builder still mixing concept catalogs, extraction I/O, and derived-metric policy in one module?
12. Any text pipeline module still mixing record preprocessing and metric hit aggregation/evidence policy in one file?
13. Any policy module still mixing payload parsing and scoring/risk decision logic in one file?
14. Any `run_*` use-case still mixing context loading, calculator execution, and completion-field shaping in one module?
15. Any catch-all `helpers.py` module still acting as a mixed-responsibility sink instead of capability owner modules?
16. Any domain `model_selection.py` still mixing contracts/catalog/signals/scoring/reasoning in one file?
17. Any domain `valuation/backtest.py` still mixing dataset I/O, runtime execution, drift comparison, and report shaping in one file?
18. Any shared DCF variant calculator still mixing validation, Monte Carlo distribution logic, and output/detail assembly in one file?
19. Any implementation utility still exposed via `utils.py` bucket or class static wrapper instead of direct capability service dependency?
20. Any bounded capability still split across root-prefixed modules and a sibling package, instead of one canonical package boundary?
21. Inside a canonical capability package, do module filenames still repeat the package capability token (stutter) instead of semantic owner names?
22. In dense model-builder packages, are model-specific and shared owners still mixed in one flat directory instead of `per-model + shared` subpackages?
23. In policy-oriented packages, does one module still mix independent policy capabilities (for example forward-signal adjustment + time-alignment guard) instead of separate owner services?
24. Do application modules import concrete infrastructure adapters directly instead of consuming ports with composition-root wiring?
25. Does any infrastructure registry/catalog execute bootstrap registration at import time instead of explicit/lazy accessor assembly?
26. Does any matured domain package still keep generic root owner modules (`models.py` / `services.py` / `rules.py`) instead of semantic capability owners?
27. Does any matured capability still exist as a flat `<capability>_*` module cluster at package root instead of a dedicated subpackage?

## 9. Recommended First Migration Targets

1. Rename concrete artifact `*Port` classes to `*Repository`.
2. Split provider vs aggregator in market/sec clients.
3. Remove ambiguous `skills/tools` naming in valuation path.
4. Introduce explicit `application/ports/*` and move concrete adapters to infrastructure.
5. Replace implicit registration/bootstrap with explicit app startup wiring.
