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

---

**T01 — Canonical Report Schema + Artifact Kinds**

**Goal**
Define `TA_FULL_REPORT v2` and new artifact kinds for feature, pattern, fusion, verification, and timeseries bundles.

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

---

**T04 — Features Subdomain Core (Classic + Quant)**

**Goal**
Create features subdomain with classic indicators and fracdiff quant features.

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

---

**T05 — Feature Dependency DAG**

**Goal**
Enable dependency-aware feature computation with topological sorting.

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

---

**T06 — Indicator Anti-Corruption Layer**

**Goal**
Prevent third-party library leakage into domain or application layers.

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

---

**T07 — Patterns Subdomain**

**Goal**
Implement support/resistance, breakouts, trendlines, and pattern flags.

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

---

**T10 — Root Orchestration Refactor**

**Goal**
Refactor root orchestrator to coordinate subdomain facades only.

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

---

**T11 — Graph State Hygiene Guard**

**Goal**
Enforce state payload restrictions in LangGraph.

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

---

**T12 — Logging & Degraded Policies**

**Goal**
Ensure every use-case has start/completion/degraded logs per standard.

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

---

**T13 — Legacy Path Removal + Import Hygiene**

**Goal**
Remove legacy module paths and clean up imports.

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

---

**T14A — Frontend API Mapping & Schema Migration**

**Goal**
Update frontend data models and API parsing to support `TA_FULL_REPORT v2` and artifact references.

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

---

**T14B — Technical Analysis UI Components Update**

**Goal**
Update UI components to render the new artifact reference flow and diagnostic fields.

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

---

**T14C1 — Frontend Artifact Fetch: Feature Pack**

**Goal**
Enable UI to fetch and render `TA_FEATURE_PACK` artifacts on demand.

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

---

**T14C2 — Frontend Artifact Fetch: Pattern Pack**

**Goal**
Enable UI to fetch and render `TA_PATTERN_PACK` artifacts on demand.

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

---

**T14C3 — Frontend Artifact Fetch: Fusion Report**

**Goal**
Enable UI to fetch and render `TA_FUSION_REPORT` artifacts on demand.

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

---

**T14C4 — Frontend Artifact Fetch: Verification Report**

**Goal**
Enable UI to fetch and render `TA_VERIFICATION_REPORT` artifacts on demand.

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
