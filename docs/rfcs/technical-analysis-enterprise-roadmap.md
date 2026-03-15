# Enterprise Technical Analysis Roadmap (Fusion Architecture)

Date: 2026-03-12
Owner: Technical Analysis Agent
Scope: `finance-agent-core/src/agents/technical` and directly affected boundary modules

## Requirement Breakdown
- Objective: Build an enterprise-grade technical analysis capability that fuses traditional chartist indicators with quantitative features, producing auditable, stable, and explainable outputs.
- Constraints:
  - Must comply with cross-agent architecture standard (layer boundaries, naming, subdomain topology).
  - Data sources limited to free providers (primarily `yfinance`).
  - LLM outputs must remain interpretive only (no deterministic logic in LLM).
- Non-goals:
  - No paid data provider integration in this scope.
  - No live trading execution layer.

## Technical Objectives and Strategy
- Adopt a **fusion architecture** with explicit layers and subdomains:
  - Market Data (providers, data contracts)
  - Feature Engineering (classic indicators + quant features)
  - Pattern/Price Action (support/resistance, breakouts)
  - Signal Fusion (policy/decision)
  - Verification (backtest, walk-forward, robustness checks)
  - Reporting (structured artifact + LLM narration)
- Separation of deterministic logic (domain) vs orchestration (application) vs adapters (infrastructure) vs boundary contracts (interface).
- Multi-timeframe analysis as a first-class output with degrade paths.
- Runtime safety: CPU-heavy stages must be offloaded with bounded concurrency (no synchronous compute on the event loop).

## Multi-Timeframe Policy (Free Provider Constraints)
- Priority 1 (MUST): Daily (1d) + Weekly (1wk). These are stable and fully supported by `yfinance`.
- Priority 2 (SHOULD): 60m (1h) when available. `yfinance` intraday history is time-limited; therefore:
  - Provide bounded lookback (e.g., last 730 days) and emit degraded flags if insufficient.
- Priority 3 (OPTIONAL): 15m or 30m if available; not required for initial enterprise release.
- Confluence logic should work when only Daily+Weekly are present; Hourly augments but must never block.

## Artifact Strategy (Enterprise Grade)
- Allow new artifact kinds to keep report payloads small and auditable:
  - `TA_FEATURE_PACK` (high-dimensional indicators and time-series features)
  - `TA_PATTERN_PACK` (support/resistance, breakouts, pattern flags)
  - `TA_FUSION_REPORT` (final consolidated decision + diagnostics)
  - `TA_TIMESERIES_BUNDLE` (multi-timeframe raw series references)
  - `TA_VERIFICATION_REPORT` (backtest + walk-forward summaries and robustness diagnostics)
- The canonical final report remains a compact, versioned artifact referencing the above by ID.

## Layer Topology and Shared Kernel Placement
- Root: `application/`, `domain/shared/`, `interface/`, `subdomains/`
- Subdomains:
  - `market_data/` (provider + data normalization)
  - `features/` (classic indicators + quant features)
  - `patterns/` (price action detection)
  - `signal_fusion/` (policy + confluence)
  - `verification/` (backtest + walk-forward + performance gates)
- Cross-subdomain orchestration: root `application/`
- Shared types: `domain/shared/` only

## Subdomain Split Justification
- Capability boundary: Each capability has a stable API and can evolve independently (features vs patterns vs verification).
- Dependency boundary: `yfinance` adapters are isolated in market_data.
- Pipeline boundary: Multi-stage pipeline fits subdomain split (fetch -> feature -> pattern -> fusion -> verification -> report).
- Cohesion signal: Existing `technical/domain` already contains 3+ tightly coupled owners (fracdiff, backtest, signal_policy).

## Runtime Execution Model (CPU-Heavy Safety)
- All heavy compute (pattern detection, walk-forward, large feature pipelines) must be executed via `asyncio.to_thread` or an executor boundary with bounded concurrency.
- Each heavy stage must emit start/completion/degraded logs with elapsed time and input/output counts.
- Add a minimal performance baseline for walk-forward and pattern detection to prevent regressions.

## Time-Series Alignment Guard (Anti Look-Ahead)
- Introduce a `TimeAlignmentGuard` in `domain/shared/` to enforce:\n  - Strict timestamp alignment per timeframe\n  - No forward-fill across future bars\n  - Explicit handling for holidays/early closes\n  - Alignment metadata included in diagnostics (alignment gaps, rows dropped)
- Fusion must only consume aligned, guard-validated series.

## Detailed Per-File Plan

### Phase 0: Contract Reset and Backward Compatibility Decision
- Accept breaking changes to `TechnicalArtifactModel` where needed.
- Define new canonical report schema with version field, and map which fields are required vs optional.
- Update documentation to reflect breaking change policy.
- Status: Completed (2026-03-12)

### Phase 1: Subdomain Skeleton + Shared Types
- Create `domain/shared/`:
  - `timeframe.py`: `Timeframe`, `TimeframeConfig`
  - `price_bar.py`: `PriceBar`, `PriceSeries`
  - `indicator_snapshot.py`: `IndicatorSnapshot`
  - `feature_pack.py`: `FeaturePack` (classic + quant)
  - `pattern_pack.py`: `PatternPack`
  - `fusion_signal.py`: `FusionSignal`, `FusionDiagnostics`
  - `time_alignment_guard.py`: `TimeAlignmentGuard`, `AlignmentReport`
- Create `subdomains/<capability>/{domain,application,interface,infrastructure}` with minimal facades.
- Add `__init__.py` exports per subdomain; prohibit deep imports from outside.
- Status: Completed (2026-03-12)

### Phase 2: Market Data Subdomain
- Move `yahoo_ohlcv_provider.py` and `yahoo_risk_free_rate_provider.py` into `subdomains/market_data/infrastructure/`.
- Define `IMarketDataProvider` in `subdomains/market_data/application/ports.py` with typed failures.
- Add `multi_timeframe_fetch_service.py` in `subdomains/market_data/application/` to fetch D/W/60m with degrade diagnostics.
- Add cache layer in `subdomains/market_data/infrastructure/`:\n  - Daily/Weekly cached per ticker per day\n  - 60m cached per ticker for 15 minutes\n  - Cache metadata included in provider logs
- Status: Completed (2026-03-12)

### Phase 3: Features Subdomain
- Status: In progress (2026-03-12)
- Move fracdiff modules into `subdomains/features/domain/fracdiff/`.
- Add classic indicators package: `subdomains/features/domain/classic/` with RSI, SMA/EMA, ATR, VWAP, MFI, MACD (price-based).
- Create `FeatureRuntimeService` in `subdomains/features/application/`:
  - Inputs: `PriceSeriesBundle` across timeframes
  - Outputs: `FeaturePack` + references to timeseries feature artifacts
- Ensure FD-based indicators remain distinct from classic indicators to avoid definition confusion.
- Add an anti-corruption layer for third-party indicator libs:\n  - Define `IIndicatorEngine` in `subdomains/features/application/ports.py`\n  - Implement `PandasTaIndicatorEngine` in `subdomains/features/infrastructure/`\n  - Normalize outputs into `IndicatorSnapshot`/`FeaturePack` (no raw pandas-ta frames outside infrastructure)
- Add **Feature Dependency DAG** support:\n  - Allow features to declare dependencies (e.g., `FRACDIFF_RSI` depends on `RSI`)\n  - Execute with topological sort and explicit stage ordering (classic price-based → derived/quant)\n  - Emit a degraded failure if cyclic dependencies are detected
  - Notes: fracdiff domain modules moved to features subdomain; classic indicators + FeatureRuntimeService added; timeseries bundle + feature pack artifact wiring complete; feature DAG execution with degraded issue logging implemented; indicator anti-corruption layer with optional pandas-ta engine wired (2026-03-12)

### Phase 4: Patterns Subdomain
- Implement support/resistance (peak clustering + KDE bins), trendlines, breakouts.
- Add `PatternRuntimeService` to produce `PatternPack` with confidence scores and key levels.
- Store pattern outputs in `TA_PATTERN_PACK` artifact.
- Ensure pattern detection uses offloaded compute with bounded concurrency.
- Status: Completed (2026-03-12)
- Notes: patterns subdomain + pattern pack artifact + workflow integration completed (2026-03-12)

### Phase 5: Signal Fusion Subdomain
- Move `signal_policy/*` into `subdomains/signal_fusion/domain/`.
- Implement `FusionService` in `subdomains/signal_fusion/application/`:
  - Inputs: `FeaturePack`, `PatternPack`, multi-timeframe context
  - Outputs: `FusionSignal` with risk, direction, confidence, confluence matrix, conflict reasons
- Define a clear policy for conflicts between classic indicators and quant features.
- Status: Completed (2026-03-12)
- Notes: signal policy moved into signal_fusion domain; fusion runtime + `TA_FUSION_REPORT` artifact + workflow node integrated; basic alignment guard used to detect look-ahead (2026-03-12)

### Phase 6: Verification Subdomain
- Move `backtest/*` into `subdomains/verification/domain/`.
- Add performance gate baseline (fixed inputs + thresholds).
- Expose `VerificationRuntimeService` for backtest and walk-forward results.
- Ensure walk-forward is always offloaded (no synchronous execution in async nodes).
- Status: Completed (2026-03-12)
- Notes: backtest domain moved into verification; baseline gate policy + verification runtime service + TA_VERIFICATION_REPORT artifact + fixed-input tests added (workflow wiring completed in Phase 8).

### Phase 7: Reporting + Interface
- Redesign canonical report schema in `interface/contracts.py` to accept:
  - `feature_pack_id`, `pattern_pack_id`, `fusion_report_id`, `timeseries_bundle_id`
- Update `interface/serializers.py` to produce the new report payload.
- Update `interpretation_prompt_spec.py` to require commentary on: timeframe confluence, classic-vs-quant conflicts, and robustness signals.

### Phase 8: Root Application Orchestration
- Replace direct calls to fracdiff/backtest/signal_policy with subdomain application facades.
- Root `application/orchestrator` becomes a thin coordinator of subdomain runtimes.
- Graph state hygiene:\n  - LangGraph state must never contain DataFrame objects\n  - State only carries primitive scalars, Pydantic models, or artifact IDs\n  - Enforce via runtime guards in state updates
- Status: Completed (2026-03-12)
- Notes: root orchestration rewired to `data_fetch → feature_compute → pattern_compute → fusion_compute → verification_compute → semantic_translate`; semantic pipeline now uses verification reports instead of backtest/fracdiff runtime services. State hygiene guard implemented in T11.

## Old → New Mapping (High-Level)
- `domain/fracdiff/*` → `subdomains/features/domain/fracdiff/*`
- `domain/backtest/*` → `subdomains/verification/domain/*`
- `domain/signal_policy/*` → `subdomains/signal_fusion/domain/*`
- `infrastructure/market_data/*` → `subdomains/market_data/infrastructure/*`
- `application/backtest_runtime_service.py` → `subdomains/verification/application/*`
- New: `subdomains/features/domain/classic/*`
- New: `subdomains/patterns/*`

## Cohesion/Facade Plan
- Each subdomain exposes only:
  - `application` facade (runtime service, ports)
  - `interface` contracts for inputs/outputs
- All external callers import from subdomain facade or root application, never deep internal paths.

## Risk/Dependency Assessment
- Dependency risk: `pandas-ta` or `ta-lib` adoption requires environment readiness. Prefer `pandas-ta` for pure Python where possible.
- Data risk: `yfinance` intraday is limited. Hourly is best-effort, with explicit degrade logging and fallback to Daily/Weekly only.
- Migration risk: breaking `TechnicalArtifactModel` requires coordinated update to any downstream consumers.
- Runtime risk: CPU-heavy stages may exceed API timeouts unless offloaded; must enforce async offload and bounded concurrency.
- Alignment risk: multi-timeframe merges can introduce look-ahead bias if not guarded; enforce `TimeAlignmentGuard`.

## Validation and Rollout Gates
- Unit tests:
  - Indicator correctness tests (classic indicators vs known values)
  - FD pipeline regression tests
  - Pattern detection deterministic tests
  - Time alignment guard tests (no look-ahead, strict index alignment)
- Performance gates:
  - Walk-forward runtime baseline with fixed seed/timeframe
  - Feature runtime baseline with bounded lookback
  - Pattern runtime baseline with bounded lookback
- Logging compliance:
  - Start/completion/degraded logs in all use-cases
  - Structured fields: `ticker`, `timeframe`, `input_count`, `output_count`, `is_degraded`
- Import hygiene:
  - Scan for legacy paths after migration

## Assumptions/Open Questions (Resolved)
- Contract compatibility: Breaking changes allowed.
- Multi-timeframe: D/W mandatory; 60m best-effort with degrade paths.
- Dependencies: Mature indicator library allowed; prefer `pandas-ta` unless `ta-lib` is already in stack.
- Artifact kinds: New artifact kinds are allowed and recommended.

## Next Steps (If Approved)
1. Freeze canonical report schema draft with versioning and new artifact references.
2. Create subdomain skeleton and shared types.
3. Implement market_data + features subdomains first (lowest risk, highest leverage).
4. Add patterns + fusion + verification in sequence.
5. Wire caching and alignment guards before enabling multi-timeframe fusion.

---

# Appendix A: Subdomain API Contracts (Draft)

This appendix defines the **application-facing contracts** for each subdomain. These are not code, but serve as design constraints for ports/services and artifact generation.

## Common Result Envelope (Conceptual)
- `is_degraded`: bool
- `degraded_reasons`: list[str]
- `failure`: optional typed failure (code + reason + optional transport metadata)
- `artifact_id`: optional, when an artifact is produced
- `summary`: short, human-readable status (for logs/diagnostics only)

## Market Data Subdomain
**Application Facade**: `MarketDataRuntimeService`\n
- `fetch_timeseries_bundle(ticker, timeframes, lookback_policy) -> TimeseriesBundleResult`\n
  - Outputs:\n
    - `timeseries_bundle_id` (artifact ID)\n
    - `available_timeframes`\n
    - `degraded_reasons` (e.g., `INTRADAY_INSUFFICIENT_DATA`)\n
  - Notes:\n
    - MUST respect cache rules\n
    - MUST include source and caching metadata in logs\n

## Features Subdomain
**Application Facade**: `FeatureRuntimeService`\n
- `build_feature_pack(timeseries_bundle_id, options) -> FeaturePackResult`\n
  - Outputs:\n
    - `feature_pack_id`\n
    - `feature_summary` (lightweight stats for UI previews)\n
  - Notes:\n
    - MUST normalize third-party indicator outputs via `IIndicatorEngine`\n
    - MUST keep classic indicators and quant features distinct\n

## Patterns Subdomain
**Application Facade**: `PatternRuntimeService`\n
- `build_pattern_pack(timeseries_bundle_id, options) -> PatternPackResult`\n
  - Outputs:\n
    - `pattern_pack_id`\n
    - `key_levels` summary (for preview only)\n
  - Notes:\n
    - CPU-heavy detection must be offloaded\n

## Signal Fusion Subdomain
**Application Facade**: `FusionRuntimeService`\n
- `fuse_signal(feature_pack_id, pattern_pack_id, alignment_report_id, options) -> FusionResult`\n
  - Outputs:\n
    - `fusion_report_id`\n
    - `direction`, `risk_level`, `confidence`\n
    - `confluence_matrix` + `conflict_reasons`\n
  - Notes:\n
    - MUST only accept time-aligned inputs\n
    - MUST emit conflict diagnostics when signals disagree\n

## Verification Subdomain
**Application Facade**: `VerificationRuntimeService`\n
- `run_verification(timeseries_bundle_id, feature_pack_id, fusion_report_id, options) -> VerificationResult`\n
  - Outputs:\n
    - `verification_report_id`\n
    - backtest + WFA summary metrics\n
  - Notes:\n
    - CPU-heavy operations must be offloaded\n
    - MUST enforce performance baselines\n

## Root Application Orchestration
**Application Facade**: `TechnicalOrchestrator`\n
- `run_pipeline(ticker, timeframe_policy, options) -> TechnicalReportResult`\n
  - Outputs:\n
    - `ta_full_report_id`\n
    - referenced IDs: `timeseries_bundle_id`, `feature_pack_id`, `pattern_pack_id`, `fusion_report_id`, `verification_report_id`\n
  - Notes:\n
    - LangGraph state must not contain DataFrames\n
    - Only IDs and small summaries are passed between nodes\n

---

# Appendix B: Artifact Schema Draft (Versioned)

All artifacts must include `schema_version` and `as_of` timestamp. Fields below are representative; breaking changes are allowed per Phase 0.

## `TA_TIMESERIES_BUNDLE` v1
- `schema_version`: `1.0`\n
- `ticker`\n
- `as_of`\n
- `timeframes`: map of timeframe → payload\n
  - `timeframe`: `1d|1wk|1h`\n
  - `start`, `end`, `timezone`\n
  - `price_series`: map of ISO date → price\n
  - `volume_series`: map of ISO date → volume\n
  - `metadata`: trading calendar notes, missing bars, cache metadata\n

## `TA_FEATURE_PACK` v1
- `schema_version`: `1.0`\n
- `ticker`\n
- `as_of`\n
- `timeframes`:\n
  - `classic_indicators`: RSI, SMA/EMA sets, ATR, VWAP, MFI, MACD (price-based)\n
  - `quant_features`: FD metrics, z-scores, statistical strength, FD-OBV\n
- `feature_summary`: lightweight numeric summary for preview\n
- `provenance`: references to timeseries bundle and compute options\n

## `TA_PATTERN_PACK` v1
- `schema_version`: `1.0`\n
- `ticker`\n
- `as_of`\n
- `timeframes`:\n
  - `support_levels`, `resistance_levels`\n
  - `breakouts`, `trendlines`\n
  - `pattern_flags`: e.g., head-shoulders, double-top (optional)\n
  - `confidence_scores`\n
- `pattern_summary`: key levels + top 3 patterns\n

## `TA_FUSION_REPORT` v1
- `schema_version`: `1.0`\n
- `ticker`\n
- `as_of`\n
- `direction`, `risk_level`, `confidence`\n
- `confluence_matrix`: per timeframe + per signal family\n
- `conflict_reasons`: list of resolved conflicts\n
- `alignment_report`: reference to TimeAlignmentGuard output\n
- `source_artifacts`: feature/pattern bundle IDs\n

## `TA_VERIFICATION_REPORT` v1
- `schema_version`: `1.0`\n
- `ticker`\n
- `as_of`\n
- `backtest_summary`: win rate, profit factor, sharpe, max drawdown, total trades\n
- `wfa_summary`: WFA sharpe, WFE, max drawdown, period count\n
- `robustness_flags`: overfitting risk, low sample warnings\n
- `source_artifacts`: timeseries bundle + feature pack + fusion report IDs\n

## `TA_FULL_REPORT` v2 (Canonical Final Report)
- `schema_version`: `2.0`\n
- `ticker`\n
- `as_of`\n
- `direction`, `risk_level`, `confidence`\n
- `llm_interpretation`\n
- `artifact_refs`:\n
  - `timeseries_bundle_id`\n
  - `feature_pack_id`\n
  - `pattern_pack_id`\n
  - `fusion_report_id`\n
  - `verification_report_id`\n
- `summary_tags`: semantic tags for UI\n
- `diagnostics`: degrade reasons, alignment issues, cache usage\n

---

# Appendix C: TimeAlignmentGuard Design Details

## Purpose
Prevent look-ahead bias and timestamp misalignment when fusing multi-timeframe data (Daily, Weekly, 60m).\n

## Core Rules
- Enforce **no future bars**: alignment must not use data beyond the target bar timestamp.\n
- Enforce **strict index alignment**: all merged frames must share a common, validated anchor index.\n
- Enforce **explicit missing data handling**: missing bars must be tagged as gaps, not silently forward-filled across future boundaries.\n

## Alignment Report (Draft)
- `schema_version`: `1.0`\n
- `anchor_timeframe`: `1d|1wk|1h`\n
- `input_timeframes`: list of provided timeframes\n
- `alignment_window`: start/end\n
- `rows_before`, `rows_after`\n
- `dropped_rows`: count\n
- `gap_count`: count\n
- `gap_samples`: list of timestamps (bounded)\n
- `look_ahead_detected`: bool\n
- `notes`: list of warnings\n

## Execution Model
- Guard is invoked in `features` and `fusion` before any multi-timeframe join.\n
- If `look_ahead_detected` is true:\n
  - mark degraded\n
  - emit blocking warning in logs\n
  - prevent fusion and return a degraded result\n

---

# Appendix D: Fusion Decision Matrix Example (Draft)

This example illustrates how classic indicators and quant features are reconciled into a single `FusionSignal`.\n

## Inputs (Example)
- Classic indicators (Daily):\n
  - RSI: 72 (overbought)\n
  - MACD: bullish but waning\n
  - Price above SMA20 and SMA50\n
- Quant features (Daily):\n
  - FD Z-Score: +2.3 (statistical extreme)\n
  - Statistical strength: 97%\n
  - FD-OBV: -0.8 (distribution)\n
- Patterns:\n
  - Resistance at 180 with 2 touches\n
  - No confirmed breakout\n

## Decision Matrix (Conceptual)
- If classic indicators bullish AND quant features extreme + distribution:\n
  - Direction: `NEUTRAL_CONSOLIDATION`\n
  - Risk: `HIGH`\n
  - Conflict reason: `PRICE_STRENGTH_BUT_SMART_MONEY_EXITING`\n
  - Confidence: `LOW`\n

## Output (Example)
- `direction`: `NEUTRAL_CONSOLIDATION`\n
- `risk_level`: `HIGH`\n
- `confidence`: `0.34`\n
- `confluence_matrix`:\n
  - `classic`: bullish\n
  - `quant`: bearish-extreme\n
  - `pattern`: neutral\n
- `conflict_reasons`: list with the dominant conflict string\n

---

# Appendix E: Market Data Cache Policy (Draft)

## Goals
- Reduce `yfinance` rate-limit risk and improve retry/debug speed.\n
- Ensure deterministic reuse within a bounded freshness window.\n

## Cache Rules
- Daily (1d): cache per ticker per day. TTL: until end of trading day.\n
- Weekly (1wk): cache per ticker per week. TTL: until next trading week.\n
- 60m (1h): cache per ticker for 15 minutes.\n
- Cache key format (conceptual): `TA:MARKET_DATA:{ticker}:{timeframe}:{date_bucket}`.\n

## Cache Metadata (must be logged)
- `cache_hit`: bool\n
- `cache_age_seconds`\n
- `cache_bucket`\n
- `source`: provider name\n
- `rows`: returned rows\n

## Degrade Handling
- If cache missing and provider fails, return typed failure with `cache_miss=true` in logs.\n
- If provider returns empty data, mark degraded and record `empty_payload`.\n

---

# Appendix F: Verification Baseline Template (Draft)

## Purpose
- Prevent silent regressions in heavy compute paths (backtest + walk-forward).\n

## Baseline Inputs (Fixed)
- `ticker`: stable liquid ticker (e.g., `SPY` or `AAPL`)\n
- `timeframe`: `1d`\n
- `lookback`: 5y\n
- `transaction_cost`: 0.0005\n
- `train_window`: 252, `test_window`: 63\n

## Baseline Metrics (Template)
- Backtest:\n
  - `total_trades`\n
  - `sharpe_ratio`\n
  - `profit_factor`\n
  - `max_drawdown`\n
- Walk-Forward:\n
  - `wfa_sharpe`\n
  - `wfe_ratio`\n
  - `wfa_max_drawdown`\n

## Acceptance Gates
- `total_trades` must be > 0\n
- `sharpe_ratio` regression threshold: -15% max\n
- `wfa_sharpe` regression threshold: -20% max\n
- `max_drawdown` increase threshold: +15% max\n

## Failure Behavior
- Mark degraded and fail CI gate for verification module changes.\n

---

# Appendix G: Code-Ready Enforcement Checklist (Draft)

This checklist is designed to be translated into automated validations or CI gates. Each item should have a **fail condition** and a **loggable reason**.\n

## Architecture & Layering
- Ensure no `infrastructure` import occurs inside `domain` or `application` modules.\n
- Ensure `interface` modules never import `application` owners.\n
- Ensure root topology is `application/`, `domain/shared/`, `interface/`, `subdomains/` only.\n
- Ensure all external imports target subdomain facades (no deep path imports).\n

## State Hygiene
- Reject any LangGraph state that contains `pandas.DataFrame` or `Series` objects.\n
- Only allow primitives, Pydantic models, or artifact IDs in state updates.\n

## Time Alignment
- Require `TimeAlignmentGuard` to run before any fusion stage.\n
- Fail if `look_ahead_detected == true`.\n
- Log alignment gap counts and dropped rows.\n

## Provider Reliability
- All provider results must include typed failure metadata on error.\n
- Empty payload must be distinct from not-found.\n
- Cache metadata must be present for all market-data calls.\n

## Feature Engine (Anti-Corruption)
- No raw `pandas-ta` DataFrame is allowed outside infrastructure.\n
- All third-party indicator outputs must normalize into `IndicatorSnapshot`/`FeaturePack`.\n

## Runtime Safety
- CPU-heavy stages must be offloaded (`asyncio.to_thread` or executor).\n
- Bounded concurrency must be enforced for heavy compute tasks.\n
- Heavy stages must emit start/completion/degraded logs.\n

## Verification Baselines
- CI gate must assert backtest and WFA thresholds are not exceeded.\n
- If thresholds fail, mark degraded and fail the verification gate.\n

## Artifact Integrity
- All artifacts must include `schema_version` and `as_of`.\n
- `TA_FULL_REPORT` must include references to all upstream artifact IDs.\n
- Reject artifacts that exceed size limits or contain raw time series if not intended.\n
