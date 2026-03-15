# Technical Analysis Enterprise Refactor Tickets

Date: 2026-03-12
Owner: Technical Analysis Agent
Scope: `finance-agent-core/src/agents/technical` and directly affected boundary modules

## Purpose
This document converts the approved roadmap into implementation-ready tickets. Each ticket is a self-contained unit with scope, deliverables, acceptance criteria, and validation gates.

## Global Constraints (Apply to All Tickets)
- Follow cross-agent architecture standard (layer boundaries, naming, subdomain topology).
- No paid data providers. Use `yfinance` or free providers only.
- LangGraph state must never contain `pandas.DataFrame` or `Series` objects.
- All CPU-heavy compute must be offloaded with bounded concurrency.
- Artifacts must include `schema_version` and `as_of`.
- No deep imports across subdomains. Use facades.

## Ticket Order (Recommended)
1. T01
2. T02
3. T03
4. T04
5. T05
6. T06
7. T07
8. T08
9. T09
10. T10
11. T11
12. T12
13. T13
14. T14A
15. T14B
16. T14C1
17. T14C2
18. T14C3
19. T14C4
20. T15
21. T16
22. T17
23. T18

---

**T01 — Canonical Report Schema + Artifact Kinds**

**Goal**
Define `TA_FULL_REPORT v2` and new artifact kinds for feature, pattern, fusion, verification, and timeseries bundles.

**Status**
Completed (2026-03-13)

**Scope**
- Introduce versioned schemas and artifact references.
- Allow breaking changes in `TechnicalArtifactModel`.

**Deliverables**
- Updated canonical schema and serializer rules.
- New artifact kind identifiers documented.

**Impacted Files**
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/technical/interface/contracts.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/technical/interface/serializers.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/docs/rfcs/technical-analysis-enterprise-roadmap.md`

**Dependencies**
- None.

**Acceptance Criteria**
- Schema includes `schema_version`, `as_of`, and artifact references.
- `TA_FULL_REPORT v2` can be validated end-to-end with Pydantic.

**Risks**
- Breaking changes may affect downstream consumers.

**Validation**
- Schema validation tests on representative payloads.

---

**T02 — Subdomain Skeleton + Shared Types + Alignment Guard**

**Goal**
Establish subdomain structure and shared kernel types, including `TimeAlignmentGuard`.

**Status**
Completed (2026-03-12)

**Scope**
- Create `domain/shared/` for shared contracts.
- Create `subdomains/<capability>/{domain,application,interface,infrastructure}` skeletons.

**Deliverables**
- Shared types: `Timeframe`, `PriceSeries`, `IndicatorSnapshot`, `FeaturePack`, `PatternPack`, `FusionSignal`.
- Alignment guard contract and report shape.

**Impacted Files**
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/technical/domain/shared/**`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/technical/subdomains/**`

**Dependencies**
- T01

**Acceptance Criteria**
- Subdomain packages import cleanly and pass layering checks.
- `TimeAlignmentGuard` contract defined with report fields.

**Risks**
- Misplaced shared types could violate architecture standard.

**Validation**
- Import hygiene checks and static lint.

---

**T03 — Market Data Subdomain + Cache**

**Goal**
Move market data providers into subdomain and add cache policy with metadata logging.

**Status**
Completed (2026-03-12)

**Scope**
- Relocate `yfinance` providers.
- Implement multi-timeframe fetch (1d, 1wk, 1h best-effort).
- Implement cache with TTL policy.

**Deliverables**
- `MarketDataRuntimeService` facade.
- Cache metadata included in provider logs.

**Impacted Files**
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/technical/subdomains/market_data/**`

**Dependencies**
- T02

**Acceptance Criteria**
- Fetch returns bundle artifact ID with available timeframes and degraded reasons.
- Cache hit/miss is logged with TTL metadata.

**Risks**
- `yfinance` intraday limits may cause frequent degrade.

**Validation**
- Provider tests covering empty payload vs not found vs degraded.

**Notes**
- Added subdomain facade export and removed legacy market_data shim (2026-03-12).

---

**T04 — Features Subdomain Core (Classic + Quant)**

**Goal**
Create features subdomain with classic indicators and fracdiff quant features.

**Status**
Completed (2026-03-12)

**Scope**
- Migrate fracdiff logic into subdomain.
- Add classic indicators (RSI, SMA/EMA, ATR, VWAP, MFI, MACD).
- Create `FeatureRuntimeService` to output `FeaturePack`.

**Deliverables**
- Feature pack artifact with classic and quant partitions.

**Impacted Files**
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/technical/subdomains/features/**`

**Dependencies**
- T02
- T03

**Acceptance Criteria**
- `FeaturePack` generated from timeseries bundle.
- Classic and quant features clearly separated in schema.

**Risks**
- Indicator correctness drift if formulas differ from reference.

**Validation**
- Indicator correctness tests against known values.
- FD regression tests.

**Notes**
- Moved fracdiff domain modules into `subdomains/features/domain/fracdiff` and updated imports (2026-03-12).
- Added classic indicator services and `FeatureRuntimeService` to produce `FeaturePack` (2026-03-12).
- Wired timeseries bundle + feature pack artifacts into workflow (2026-03-12).

---

**T05 — Feature Dependency DAG**

**Goal**
Enable dependency-aware feature computation with topological sorting.

**Status**
Completed (2026-03-12)

**Scope**
- Define feature dependency declaration format.
- Implement DAG execution order and cycle detection.

**Deliverables**
- Topological execution in `FeatureRuntimeService`.
- Degraded failure on cycle.

**Impacted Files**
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/technical/subdomains/features/application/**`

**Dependencies**
- T04

**Acceptance Criteria**
- `FRACDIFF_RSI` or similar derived features compute reliably.
- Cyclic dependencies cause degraded result and error log.

**Risks**
- DAG adds complexity to debugging and performance.

**Validation**
- Unit tests for DAG order and cycle detection.

**Notes**
- Added `feature_dependency_dag.py` with stage-aware topological planning and cycle detection (2026-03-12).
- Wired `FeatureRuntimeService` to execute feature tasks through the DAG with quant/classic stage ordering and degraded issue logging (2026-03-12).

---

**T06 — Indicator Anti-Corruption Layer**

**Goal**
Prevent third-party library leakage into domain or application layers.

**Status**
Completed (2026-03-12)

**Scope**
- Define `IIndicatorEngine` port.
- Implement `PandasTaIndicatorEngine` in infrastructure.
- Normalize outputs into `IndicatorSnapshot` and `FeaturePack` only.

**Deliverables**
- No raw `pandas-ta` DataFrame outside infrastructure.

**Impacted Files**
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/technical/subdomains/features/application/ports.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/technical/subdomains/features/infrastructure/**`

**Dependencies**
- T04

**Acceptance Criteria**
- Normalized output schema is stable regardless of library implementation.

**Risks**
- API mismatch or library changes can break normalization.

**Validation**
- Contract tests with synthetic inputs.

**Notes**
- Added `IIndicatorEngine` port and normalized result contracts in features application (2026-03-12).
- Added `PandasTaIndicatorEngine` with optional pandas-ta dependency handling and structured failure logging (2026-03-12).
- Wired `FeatureRuntimeService` to use the engine when available and fall back to internal classic indicator tasks (2026-03-12).

---

**T06a — fracdiff Dependency Audit**

**Goal**
Explain why the `fracdiff` library dependency is unused and decide whether to reintroduce or remove it permanently.

**Status**
Completed (2026-03-12)

**Scope**
- Audit usages of `fracdiff` package vs internal fracdiff implementation.
- Document rationale for internal implementation or migration plan to external library.
- Decide final dependency posture.

**Deliverables**
- Short audit note with findings and decision.

**Impacted Files**
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/pyproject.toml`
- `/Users/denniswong/Desktop/Project/value-investment-agent/docs/rfcs/technical-analysis-enterprise-tickets.md`

**Dependencies**
- T06

**Acceptance Criteria**
- Clear reason captured for `fracdiff` dependency being unused.
- Explicit decision: re-add or keep removed.

**Risks**
- Re-adding may conflict with `numpy>=2.2.6` if package pins `numpy<2.0`.

**Validation**
- `rg` shows no remaining imports of external `fracdiff` package.

**Notes**
- No `import fracdiff` usages found; fractional differencing uses internal implementations in `subdomains/features/domain/fracdiff/*` (2026-03-12).
- External `fracdiff` dependency was removed to unblock `pandas-ta` (it pins `numpy<2.0`), with no runtime impact since the codebase does not call it (2026-03-12).
- Decision: keep removed unless a future migration plan justifies reintroducing via optional dependency (2026-03-12).

---

**T06b — Fracdiff Engine Benchmark & Validation**

**Goal**
Establish a repeatable benchmark to compare internal fracdiff against an external engine (e.g., `fracdiff-modern`) before any migration decision.

**Scope**
- Define fixed input series and expected tolerance bands.
- Implement test harness to compare internal vs external outputs.
- Record performance and accuracy deltas.

**Deliverables**
- Benchmark report + test harness.

**Impacted Files**
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/tests/**`
- `/Users/denniswong/Desktop/Project/value-investment-agent/docs/rfcs/technical-analysis-enterprise-tickets.md`

**Dependencies**
- T06a

**Acceptance Criteria**
- Internal vs external outputs compared with explicit tolerance thresholds.
- Clear recommendation recorded (keep internal, adopt external, or hybrid).

**Risks**
- External engine may introduce dependency conflicts.

**Validation**
- Benchmarks run with pinned inputs.

---

**T07 — Patterns Subdomain**

**Goal**
Implement support/resistance, breakouts, trendlines, and pattern flags.

**Status**
Completed (2026-03-12)

**Scope**
- New patterns domain and runtime.
- Pattern outputs stored as `TA_PATTERN_PACK`.

**Deliverables**
- Pattern pack artifact with confidence scores and key levels.

**Impacted Files**
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/technical/subdomains/patterns/**`

**Dependencies**
- T02
- T03

**Acceptance Criteria**
- Pattern pack produced for daily and weekly inputs.
- CPU-heavy steps are offloaded.

**Risks**
- KDE or peak detection can be sensitive to noise.

**Validation**
- Deterministic pattern tests with fixed seed inputs.

**Notes**
- Added patterns subdomain with detection services and runtime (2026-03-12).
- Added `TA_PATTERN_PACK` artifact schema + repository support, and wired pattern compute into workflow (2026-03-12).

---

**T08 — Signal Fusion Subdomain**

**Goal**
Fuse classic indicators, quant features, and patterns into a single `FusionSignal`.

**Scope**
- Implement confluence matrix and conflict diagnostics.
- Enforce alignment guard prior to fusion.

**Deliverables**
- `TA_FUSION_REPORT` artifact with conflict reasons.

**Impacted Files**
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/technical/subdomains/signal_fusion/**`

**Dependencies**
- T04
- T05
- T07
- T02

**Acceptance Criteria**
- Fusion emits direction, risk, confidence, confluence matrix.
- Conflicts are captured in diagnostics.

**Risks**
- Policy tuning may be subjective without calibration data.

**Validation**
- Fusion policy unit tests on canonical scenarios.

**Status**
- Completed (2026-03-12)

**Notes**
- Moved `signal_policy` into `subdomains/signal_fusion/domain` and rewired imports.
- Added `FusionRuntimeService` + `TA_FUSION_REPORT` artifact + workflow node between patterns and fracdiff.
- Added basic time alignment guard usage in fusion compute with look-ahead detection.

---

**T09 — Verification Subdomain + Baseline Gate**

**Goal**
Move backtest and walk-forward into verification subdomain with baseline gates.

**Scope**
- Implement `TA_VERIFICATION_REPORT` artifact.
- Add performance baseline and regression thresholds.

**Deliverables**
- Baseline metrics and CI gate specification.

**Impacted Files**
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/technical/subdomains/verification/**`

**Dependencies**
- T02
- T04

**Acceptance Criteria**
- WFA and backtest results generated and logged.
- Baseline gates enforce thresholds.

**Risks**
- Baseline drift if data source changes.

**Validation**
- Baseline gate tests with fixed inputs.

**Status**
- Completed (2026-03-12)

**Notes**
- Backtest domain moved into `subdomains/verification/domain` with facade exports.
- Added baseline gate policy + verification runtime service + `TA_VERIFICATION_REPORT` artifact wiring.
- Added fixed-input tests for baseline gate and verification runtime; workflow integration deferred to T10.

---

**T10 — Root Orchestration Refactor**

**Goal**
Refactor root orchestrator to coordinate subdomain facades only.

**Status**
Completed (2026-03-12)

**Scope**
- Replace direct calls to old fracdiff/backtest/policy.
- Connect new artifact IDs through pipeline.

**Deliverables**
- End-to-end pipeline built on subdomain facades.

**Impacted Files**
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/technical/application/**`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/technical_analysis/**`

**Dependencies**
- T03
- T04
- T05
- T07
- T08
- T09

**Acceptance Criteria**
- Pipeline produces `TA_FULL_REPORT v2` plus upstream artifacts.

**Risks**
- Integration complexity may reveal mismatched contracts.

**Validation**
- Integration smoke test with a stable ticker.

**Notes**
- T10-S1: added verification compute use-case + state contract wiring (no graph rewiring).
- T10-S2: rewired workflow to `verification_compute`, removed root wiring to fracdiff/backtest runtimes, and switched semantic pipeline to load verification reports for LLM context.

---

**T11 — Graph State Hygiene Guard**

**Goal**
Enforce state payload restrictions in LangGraph.

**Status**
Completed (2026-03-12)

**Scope**
- Add runtime guard to reject DataFrame and Series objects.
- Ensure state updates only carry IDs or small summaries.

**Deliverables**
- Guard logic and clear error logging.

**Impacted Files**
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/technical/application/state_updates.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/state.py`

**Dependencies**
- T10

**Acceptance Criteria**
- State rejects non-allowed payload types.

**Risks**
- Hidden large payloads in nested structures may slip through without deep checks.

**Validation**
- Guard tests using synthetic state payloads.

**Notes**
- Added recursive payload scan for pandas DataFrame/Series and a state update guard that emits structured errors.

---

**T12 — Logging & Degraded Policies**

**Goal**
Ensure every use-case has start/completion/degraded logs per standard.

**Status**
Completed (2026-03-12)

**Scope**
- Update each subdomain application use-case.
- Add structured fields and error codes.

**Deliverables**
- Consistent log fields across all use-cases.

**Impacted Files**
- All `application/**` modules within subdomains.

**Dependencies**
- T03 to T10

**Acceptance Criteria**
- Every node path emits start and completion logs.

**Risks**
- Logging drift if new paths are added without templates.

**Validation**
- Log schema tests or lint rule.

**Notes**
- Added `input_count` / `output_count` to completion + degraded logs across technical use-cases (feature, pattern, fusion, verification, data_fetch, semantic_translate, legacy fracdiff).

---

**T13 — Legacy Path Removal + Import Hygiene**

**Goal**
Remove legacy module paths and clean up imports.

**Status**
Completed (2026-03-12)

**Scope**
- Replace old paths with subdomain facades.
- Remove compatibility shims.

**Deliverables**
- No legacy imports remain.

**Impacted Files**
- Any module referencing `technical/domain/*` or legacy `infrastructure/market_data/*`.

**Dependencies**
- T10

**Acceptance Criteria**
- `rg` scan shows no legacy paths.

**Risks**
- Hidden indirect imports may break at runtime.

**Validation**
- Import hygiene sweep and unit tests.

**Notes**
- Hygiene guard now blocks legacy `technical.domain.{fracdiff,signal_policy,backtest}` and `technical.infrastructure.market_data` imports.
- Legacy infrastructure market data modules confirmed removed; no remaining legacy-path imports in codebase.

---

**T14A — Frontend API Mapping & Schema Migration**

**Goal**
Update frontend data models and API parsing to support `TA_FULL_REPORT v2` and artifact references.

**Status**
Completed (2026-03-12)

**Scope**
- Update API response mapping to read `artifact_refs` instead of legacy inline payloads.
- Add explicit handling for missing optional artifacts and degraded paths.
- Update any frontend types/interfaces for the new report schema.

**Deliverables**
- Frontend parsing layer aligned to `TA_FULL_REPORT v2`.
- Backward-incompatible fields removed or gated.

**Impacted Files**
- `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/**`
- Any API response mapping used by frontend.

**Dependencies**
- T01
- T10

**Acceptance Criteria**
- API responses parse without runtime errors for the new schema.
- Degraded reports render without crashes.

**Risks**
- Silent UI failures if schema mismatch remains.

**Validation**
- Frontend smoke test on a known ticker.
- Snapshot tests updated (if available).

**Notes**
- Enforced `TA_FULL_REPORT v2` parsing only (legacy schema removed).
- Added `chart_data_id` handling to artifact references.

---

**T14B — Technical Analysis UI Components Update**

**Goal**
Update UI components to render the new artifact reference flow and diagnostic fields.

**Status**
Completed (2026-03-13)

**Scope**
- Update technical analysis cards to show `feature_pack_id`, `pattern_pack_id`, `fusion_report_id`, `verification_report_id` references.
- Display confluence/conflict diagnostics and degrade reasons.
- Hide or soften sections when optional artifacts are missing.

**Deliverables**
- UI renders new fields and diagnostics.
- Graceful display for partial data.

**Impacted Files**
- `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/**`

**Dependencies**
- T14A

**Acceptance Criteria**
- UI shows new report sections without layout regressions.
- Missing artifacts produce clear, non-breaking messaging.

**Risks**
- Visual regressions due to added sections.

**Validation**
- UI smoke test with a known ticker.
- Visual snapshot comparison (if available).

**Notes**
- Updated technical analysis UI to render v2 summary (direction, risk, confidence, summary tags, diagnostics, artifact references).
- Removed legacy chart fallback; charting now pulls `ta_chart_data` via `chart_data_id`.

---

**T14C1 — Frontend Artifact Fetch: Feature Pack**

**Goal**
Enable UI to fetch and render `TA_FEATURE_PACK` artifacts on demand.

**Status**
Completed (2026-03-12)

**Scope**
- Implement artifact fetch flow for feature packs.
- Add drilldown/expandable UI section for feature details.
- Cache feature artifact responses client-side.

**Deliverables**
- UI renders feature pack sections without blocking top-level report.

**Impacted Files**
- `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/**`

**Dependencies**
- T14A
- T10

**Acceptance Criteria**
- Feature pack can be fetched and rendered for a known ticker.
- Fetch failure shows non-blocking warning.

**Risks**
- Large artifact payloads could affect UI performance if not cached.

**Validation**
- Manual drilldown test for feature pack.

**Notes**
- Added `TA_FEATURE_PACK` parsing, artifact kind support, and expandable UI section with summary counts and highlights.

---

**T14C2 — Frontend Artifact Fetch: Pattern Pack**

**Goal**
Enable UI to fetch and render `TA_PATTERN_PACK` artifacts on demand.

**Status**
Completed (2026-03-12)

**Scope**
- Implement artifact fetch flow for pattern packs.
- Add drilldown/expandable UI section for pattern details.
- Cache pattern artifact responses client-side.

**Deliverables**
- UI renders pattern pack sections without blocking top-level report.

**Impacted Files**
- `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/**`

**Dependencies**
- T14A
- T10

**Acceptance Criteria**
- Pattern pack can be fetched and rendered for a known ticker.
- Fetch failure shows non-blocking warning.

**Risks**
- Pattern artifact size may impact UI rendering.

**Validation**
- Manual drilldown test for pattern pack.

**Notes**
- Added `TA_PATTERN_PACK` parsing, artifact kind support, and expandable UI section with level/flag summaries and highlights.

---

**T14C3 — Frontend Artifact Fetch: Fusion Report**

**Goal**
Enable UI to fetch and render `TA_FUSION_REPORT` artifacts on demand.

**Status**
Completed (2026-03-12)

**Scope**
- Implement artifact fetch flow for fusion reports.
- Add drilldown/expandable UI section for confluence/conflict diagnostics.
- Cache fusion artifact responses client-side.

**Deliverables**
- UI renders fusion diagnostics without blocking top-level report.

**Impacted Files**
- `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/**`

**Dependencies**
- T14A
- T10

**Acceptance Criteria**
- Fusion report can be fetched and rendered for a known ticker.
- Fetch failure shows non-blocking warning.

**Risks**
- Complex diagnostics may require new UI components.

**Validation**
- Manual drilldown test for fusion report.

**Notes**
- Added `TA_FUSION_REPORT` parsing, artifact kind support, and expandable UI section with confluence matrix and conflict tags.

---

**T14C4 — Frontend Artifact Fetch: Verification Report**

**Goal**
Enable UI to fetch and render `TA_VERIFICATION_REPORT` artifacts on demand.

**Status**
Completed (2026-03-12)

**Scope**
- Implement artifact fetch flow for verification reports.
- Add drilldown/expandable UI section for backtest/WFA summaries.
- Cache verification artifact responses client-side.

**Deliverables**
- UI renders verification summaries without blocking top-level report.

**Impacted Files**
- `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/**`

**Dependencies**
- T14A
- T10

**Acceptance Criteria**
- Verification report can be fetched and rendered for a known ticker.
- Fetch failure shows non-blocking warning.

**Risks**
- Backtest summaries may require new visualization patterns.

**Validation**
- Manual drilldown test for verification report.

**Notes**
- Added `TA_VERIFICATION_REPORT` parsing, artifact kind support, and expandable UI section with baseline gates + backtest/WFA summaries.

---

**T15 — Timeseries Bundle OHLC Expansion (B‑Ready)**

**Goal**
Expand `ta_timeseries_bundle` to include OHLC series for candlestick rendering and indicator accuracy.

**Status**
Completed (2026-03-13)

**Effort Estimate**
Medium (2–3 days)

**Scope**
- Extend `TechnicalTimeseriesFrameData` with OHLC series.
- Update market data providers to return OHLC data.
- Update frontend parsers/types for OHLC.
- Normalize all timestamps to UTC and persist timezone metadata per timeframe.

**Deliverables**
- Timeseries bundle includes OHLC for each timeframe when available.
- Degraded reasons recorded when OHLC is missing.

**Impacted Files**
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/interface/artifacts/artifact_data_models.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/technical/subdomains/market_data/**`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/technical/subdomains/artifacts/infrastructure/technical_artifact_repository.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/types/agents/technical.ts`
- `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/types/agents/artifact-parsers.ts`

**Dependencies**
- T03

**Acceptance Criteria**
- OHLC present in bundle for at least daily timeframe.
- Missing OHLC yields degraded reason rather than crash.
- All OHLC series indices are UTC-normalized and strictly aligned.

**Risks**
- OHLC gaps for intraday data.
- Payload size increase.
- Timezone drift or DST ambiguity causing misaligned charts.

**Validation**
- Unit tests for OHLC mapping.
- Artifact schema tests for new fields.
- Timezone normalization tests using DST boundary samples.

**Notes**
- No compatibility shims allowed; schema will be updated in place.
- Enforce UTC normalization at the market data boundary (no local time in artifacts).
- T15-S1: backend OHLC schema + provider + bundle updates completed.
- T15-S2: frontend types/envelope/parsers updated for `ta_timeseries_bundle`.

---

**T16 — Indicator Series Artifact (MTF, B‑Ready)**

**Goal**
Generate multi‑timeframe indicator series for RSI/MACD/SMA/EMA/VWAP/MFI/ATR/FD to power B‑grade chart panels.

**Status**
Completed (2026-03-13)

**Effort Estimate**
Large (4–6 days)

**Scope**
- Introduce `ta_indicator_series` artifact kind.
- Compute series per timeframe and persist in a single artifact.
- Add `indicator_series_id` to `artifact_refs`.
- Add warm-up period rules for long lookback indicators (e.g., SMA/EMA/ATR).
- Add downsampling policy for large series payloads.

**Deliverables**
- Indicator series artifact with `timeframes` map (daily/weekly/60m).
- Frontend parser support for indicator series.
- Documented warm-up strategy and max-points sampling policy.

**Impacted Files**
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/shared/kernel/contracts.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/interface/artifacts/artifact_data_models.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/technical/subdomains/features/**`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/technical/application/use_cases/**`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/technical/interface/contracts.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/types/agents/technical.ts`
- `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/types/agents/artifact-parsers.ts`

**Dependencies**
- T15

**Acceptance Criteria**
- Series output aligns with latest snapshot values (tolerance‑based).
- UI can fetch indicator series without blocking top‑level report.
- Warm-up periods do not leak NaNs into the visible window.

**Risks**
- CPU cost for series generation on large windows.
- Time alignment bugs across timeframes.
- Payloads grow into multi‑MB range without sampling.

**Validation**
- Snapshot vs series consistency tests.
- Alignment guard tests for each timeframe.
- Downsampling unit tests on synthetic long series.

**Notes**
- Decision: single artifact containing all timeframes for maintainability and fewer refs.
- Consider FastAPI `GZipMiddleware` on artifact endpoints once series size exceeds threshold.
- T16-S1: added `ta_indicator_series` artifact contract + data model and `indicator_series_id` in technical report refs/state.
- T16-S2: repository + ports wired for `ta_indicator_series` storage.
- T16-S3: indicator series runtime + feature compute wiring to emit `indicator_series_id`.
- T16-S4: frontend types + parsers for `ta_indicator_series`.
- T16-S5: frontend output wiring to fetch indicator series and show summary in advanced panel.

---

**T17 — Frontend B‑Grade Dashboard (Price + Indicators + MTF)**

**Goal**
Deliver B‑grade UI: candlestick price chart, volume, indicator panels, and multi‑timeframe overview.

**Status**
Completed (2026-03-13)

**Effort Estimate**
Large (4–7 days)

**Scope**
- Add candlestick price chart + volume.
- Add RSI/MACD/FD indicator panels.
- Add MTF summary table and timeframe switcher.
- Add crosshair synchronization across panels.
- Add artifact cache manager for large series payloads.

**Deliverables**
- B‑grade dashboard with price + indicator panels.
- Crosshair-synced multi-panel experience.

**Impacted Files**
- `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/components/agent-outputs/TechnicalAnalysisOutput.tsx`
- `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/types/agents/technical.ts`
- `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/types/agents/artifact-parsers.ts`

**Dependencies**
- T15
- T16

**Acceptance Criteria**
- Candlestick chart renders from OHLC.
- Indicator panels render from series artifact for all timeframes.
- Crosshair sync works across price + indicator panels.

**Risks**
- Chart library integration complexity.
- UI performance with large series payloads.
- Cache misses increase redundant artifact fetches.

**Validation**
- UI smoke test for D/W/60m.
- Performance test with large series payload.
- Crosshair sync UX test.

**Notes**
- Recommended chart lib: `lightweight-charts` (TradingView) for performance and finance focus.
- Cache manager can be a dedicated SWR config with long `dedupingInterval` for large artifacts.
- T17-S1: added `lightweight-charts` dependency, new `TechnicalCandlestickChart` component, and OHLCV panel wired to `ta_timeseries_bundle`.
- Note: lightweight-charts license requires a TradingView attribution/link in the UI (can use `attributionLogo` option).
- T17-S2: added RSI/MACD/FD indicator panels using `ta_indicator_series` with lightweight-charts.
- T17-S3: crosshair sync across price + indicator panels and timeframe-linked indicator views.
- T17-S4: added MTF coverage table and extended artifact cache TTL for large series payloads.

---

**T18 — Alert Signals (Threshold + Breakout)**

**Goal**
Add B‑grade alert outputs for thresholds (RSI/FD Z‑Score) and breakout events.

**Status**
Completed (2026-03-14)

**Effort Estimate**
Medium (2–4 days)

**Scope**
- Define alert rules in domain (threshold/breakout).
- Produce `ta_alerts` artifact.
- Add UI panel for alert summaries.
- Add severity classification (info/warn/critical).

**Deliverables**
- Alert artifact with rule‑based signals and timestamps.
- Severity labels and a prioritized alert list.

**Impacted Files**
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/interface/artifacts/artifact_data_models.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/shared/kernel/contracts.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/technical/application/use_cases/**`
- `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/components/agent-outputs/TechnicalAnalysisOutput.tsx`

**Dependencies**
- T16
- T14C2

**Acceptance Criteria**
- Alerts emitted for synthetic threshold/breakout test cases.
- UI displays alert summary without blocking main report.
- Severity ordering shown in UI.

**Risks**
- False positives due to noisy data.
- Alert volume could overwhelm UI if not filtered.

**Notes**
- T18-S1: added `ta_alerts` artifact kind, data model, repository port, and `alerts_id` wiring in technical report refs/state contract.
- T18-S2: added alerts runtime + use case, workflow node, and state updates to emit `alerts_id`.
- T18-S3: added frontend artifact parsing + alert signals panel with severity-ordered list.

**Validation**
- Unit tests for alert rule evaluation.
- End‑to‑end artifact rendering test.
- Severity classification unit tests.

---

**B‑Phase Execution Order (T15–T18)**

**Order**
1. **T15** — OHLC expansion (schema + provider + bundle)
2. **T16** — Indicator series artifact (compute + storage + refs)
3. **T17** — Frontend B‑grade dashboard (candlestick + panels + MTF)
4. **T18** — Alerts (threshold + breakout + severity)

**Entry/Exit Criteria Per Step**
- T15 exit: daily OHLC available with UTC‑normalized timestamps; bundle validation passes.
- T16 exit: indicator series artifact created, `indicator_series_id` set in refs, downsampling policy enforced.
- T17 exit: candlestick + indicator panels render for D/W/60m; crosshair sync verified.
- T18 exit: alert artifact produced and severity ordering shown in UI.

---

**B‑Phase Risk Mitigation Plan**

**Timezone & Alignment**
- Enforce UTC at provider boundary and store timezone metadata.
- Add alignment guard checks in pre‑artifact validation.

**Payload Growth**
- Apply downsampling policy for long series before artifact persist.
- Enable response compression (`GZipMiddleware`) once payload size exceeds threshold.

**Frontend Performance**
- Add artifact cache manager (SWR long `dedupingInterval` + size‑aware memoization).
- Avoid rendering all timeframes simultaneously unless explicitly requested.

**Chart Library Constraints**
- Use `lightweight‑charts` with required TradingView attribution.
- Validate crosshair sync across all panels before rollout.

**Alert Noise**
- Add severity thresholds and suppress low‑value alerts by default.
- Require at least one confirmation indicator for “critical” alerts.
