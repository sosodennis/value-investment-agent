# Progress Log

## Session Start
- **Date**: 2026-03-19
- **Epic**: `20260319-technical-p1-quant-core-epic`
- **Goal**: Ship the free-data-compatible `P1 core` technical quant layer and integrate it into the technical evidence engine without widening scope into macro, premium-data signals, or full calibration.

## Context Recovery Block
- **Current child**: #3 — Implement normalized distance quant family
- **Current status**: READY
- **Current artifact**: `SUBTASKS.csv`
- **Key context**:
  - The formally adopted project direction is now:
    - `Technical first`
    - `Free-data-first`
    - `Deterministic scoring first`
    - `LLM for explanation only`
    - `Evidence engine before macro expansion`
    - `Calibration backbone before full calibration program`
  - The `P1 core` feature families are:
    - volatility regime
    - liquidity proxy
    - normalized distance
    - cross-timeframe alignment
  - `momentum_extremes` is already shipped and should be treated as an existing readout surface, not as unfinished scope inside this epic.
  - `persistence` and `structural break` were intentionally moved out of this epic into `P1.5 / early P2`.
  - Before creating this epic, the base was hardened by:
    - fixing the stale fundamental hygiene guard
    - moving avoidable technical artifact serialization from `application` into `technical/interface`
- **Next action**: Start child task #3 and land normalized distance features in a medium-safe slice.

## 2026-03-20 Update
- **Child #1 completed**: volatility regime quant family
- **What landed**:
  - `VOL_REALIZED_20`
  - `VOL_DOWNSIDE_20`
  - `VOL_PERCENTILE_252`
- **Why this matters**:
  - gives the `P1 core` roadmap its first market-state quant family using only free-data-compatible OHLCV inputs
  - keeps deterministic scoring ownership inside backend feature modules
  - preserves the sequencing rule that evidence/readout integration waits until multiple `P1 core` families exist
- **Validation snapshot**:
  - targeted feature/use-case pytest: `38 passed`
  - targeted ruff on changed technical feature paths: passed
  - technical import hygiene + artifact API contract checks: `9 passed`

## 2026-03-20 Update #2
- **Child #2 completed**: liquidity proxy quant family
- **What landed**:
  - `DOLLAR_VOLUME_20`
  - `AMIHUD_ILLIQUIDITY_20`
  - `DOLLAR_VOLUME_PERCENTILE_252`
- **Why this matters**:
  - adds the first free-data liquidity context family without requiring microstructure or premium feeds
  - strengthens later reliability/evidence integration with deterministic volume-aware context
  - keeps numeric scoring ownership inside backend feature modules and out of the UI/LLM path
- **Validation snapshot**:
  - targeted feature/liquidity pytest: `11 passed`
  - targeted ruff on changed technical feature paths: passed
  - technical import hygiene + artifact API contract checks: `9 passed`

## Planning Notes
- **Execution policy**:
  - use `taskmaster` truth artifacts for epic tracking
  - use `agent-refactor-executor` for implementation slices
  - use `architecture-standard-enforcer` as the compliance gate after changed-path validation
- **Critical sequencing**:
  - each feature family should land with deterministic contract semantics, not as an isolated formula
  - evidence/readout integration should wait until the four `P1 core` families exist
  - frontend should only consume backend-owned deterministic summaries
- **Guardrails**:
  - no macro expansion in this epic
  - no premium-data assumptions
  - no LLM-owned runtime scoring
  - no giant composite alpha score
