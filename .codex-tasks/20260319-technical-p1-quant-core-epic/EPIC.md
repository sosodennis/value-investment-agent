# EPIC: Technical P1 Core Quant Layer

## Goal
Implement the free-data-compatible `P1 core` technical quant layer so the technical agent evolves from classic-indicator-only directionality into a stronger deterministic evidence engine with market context and reliability-aware readouts.

## Scope
- T41: Add volatility regime quant features and integrate them into technical artifacts.
- T42: Add liquidity proxy quant features and integrate them into technical artifacts.
- T43: Add normalized distance quant features and integrate them into technical artifacts.
- T44: Add cross-timeframe alignment quant features and integrate them into technical artifacts.
- T45: Integrate the new quant families into evidence/readout surfaces, finalize validation, and close rollout hygiene.

## Constraints
- Follow the formally adopted project direction:
  - `Technical first`
  - `Free-data-first`
  - `Deterministic scoring first`
  - `LLM for explanation only`
  - `Evidence engine before macro expansion`
  - `Calibration backbone before full calibration program`
- Preserve current root topology: `application / domain / interface / subdomains`.
- No compatibility shims.
- No paid-data dependency and no premium-only signal assumptions.
- Keep runtime numeric logic deterministic and backend-owned.

## Non-Goals
- Do not introduce macro as a hard dependency.
- Do not add options-implied or microstructure features.
- Do not implement full calibrated confidence.
- Do not start `P1.5` families (`persistence` / `structural break`) in this epic.
- Do not re-open already shipped `momentum_extremes` readout work; treat it as an existing capability outside this epic.

## Risk Assessment
- Feature sprawl risk: quant additions can become a bag of indicators unless evidence/readout integration stays consistent.
- Data-quality risk: free-source intraday limitations must not silently degrade deterministic outputs.
- Contract risk: new quant features must align with the hardened technical artifact surface instead of reintroducing loose payloads.
- Fusion risk: quant context should improve state/reliability semantics without collapsing into a black-box mega score.

## Child Deliverables
- Volatility-regime quant family.
- Liquidity-proxy quant family.
- Normalized-distance quant family.
- Cross-timeframe-alignment quant family.
- Integration/readout/validation closeout.

## Dependency Notes
- T45 depends on T41;T42;T43;T44 because evidence/readout integration should consume the stabilized feature families rather than partial prototypes.
- T41-T44 are intentionally parallelizable at the planning level, but implementation should still avoid overlapping write scopes within a slice.

## Child Task Types
- `single-compact`
- `single-full`
- `batch`

## Done-When
- [ ] Every row in `SUBTASKS.csv` is `DONE`
- [ ] New P1 quant features are present in technical artifacts with deterministic contracts
- [ ] Evidence/readout surfaces consume the new features without frontend-local re-derivation
- [ ] Final backend/frontend validation passes
