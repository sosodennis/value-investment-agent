# Fundamental S3-lite SEC + yfinance Dilution Proxy Plan (2026-03-08)

## Requirement Breakdown
1. Objective
- Implement `S3-lite` for DCF denominator handling using only SEC + yfinance inputs.
- Keep `S1/S2` intact:
  - `S1`: FCFF-WACC path with deterministic fallback.
  - `S2`: no SBC addback + conservative denominator baseline.
- Add dilution-proxy adjustment only (no option fair-value model).

2. Success Criteria
- Under same replay input, system can emit explainable denominator path:
  - `raw shares` -> `conservative shares` -> `dilution-proxy adjusted shares`.
- If SEC dilution inputs are missing/invalid, deterministic fallback applies and is logged.
- Existing DCF graph math remains unchanged; only parameterization denominator policy is extended.
- Targeted tests and lint pass with no architecture-boundary regressions.

3. Constraints
- Direct rollout, no feature flag.
- Preserve existing logging and assumption traceability style.
- No option fair-value inputs (strike/term/vol pricing) in this round.

4. Out of Scope
- No Black-Scholes / lattice / explicit option liability deduction.
- No external premium option datasets (FactSet/Bloomberg/etc.).
- No frontend interaction redesign.
- No non-DCF valuation model behavior changes.

## Technical Objectives and Strategy
1. Data Contract Enablement
- Extend SEC extraction contracts/mappings to provide both:
  - weighted-average basic shares,
  - weighted-average diluted shares.
- Keep fields optional and fallback-safe.

2. S3-lite Denominator Policy
- In SaaS/DCF builder, compute filing dilution proxy from SEC weighted-average shares:
  - `proxy = max((diluted - basic) / basic, 0)` with bounded clamp.
- Apply proxy after S2 conservative denominator resolution:
  - `shares_effective = shares_conservative * (1 + proxy)`.
- If SEC proxy inputs are unavailable/invalid, keep S2 output unchanged and log fallback reason.

3. Observability
- Add assumption statements and shares source token to reflect:
  - proxy applied / not applied,
  - input values and clamp,
  - fallback reason.
- Keep metadata path compatible through existing `shares_outstanding_source` summary.

## Involved Files
1. SEC extraction contracts and mapping
- `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/mappings/base_core_fields.py`
- `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/base_model_context_balance_builder.py`
- `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/base_model_assembler.py`
- `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/report_contracts.py`

2. Canonical/domain contracts
- `finance-agent-core/src/agents/fundamental/interface/contracts.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/report_contract.py`

3. DCF parameterization policy
- `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/model_builders/saas/saas.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/metadata_service.py` (only if summary tokens need normalization)

4. Tests
- `finance-agent-core/tests/test_param_builder_canonical_reports.py`
- `finance-agent-core/tests/test_dcf_graph_tools.py` (regression guard only if required)

## Detailed Per-File Plan
1. `base_core_fields.py`
- Register dedicated mappings:
  - `weighted_average_shares_basic`
  - `weighted_average_shares_diluted`
- Use IS duration + shares units.

2. `base_model_context_balance_builder.py`
- Extend `ContextBalanceFields` dataclass with the two weighted-average share fields.
- Extract them via mapping registry fallback configs.

3. `base_model_assembler.py` + `report_contracts.py`
- Add fields to internal SEC base model and assembly path.

4. `interface/contracts.py` + `domain/valuation/report_contract.py`
- Add optional canonical/domain visibility for the two weighted-average fields.
- Keep compatibility by optional typing and existing traceable parsing.

5. `saas.py`
- Add helper to compute filing dilution proxy from weighted-average basic/diluted shares.
- Clamp proxy to a conservative bound and log clamp/fallback.
- Apply proxy multiplicatively to denominator after S2 conservative selection.
- Emit shares source token suffix (for example `_dilution_proxy`).

6. `metadata_service.py` (conditional)
- Ensure shares source summary can clearly indicate proxy-applied path.

7. Tests
- Add coverage for:
  - proxy applied path (basic/diluted available),
  - proxy fallback path (missing/invalid inputs),
  - no regression for existing S1/S2 behavior.

## Risk/Dependency Assessment
1. Functional risk
- Weighted-average shares (period average) differ from point-in-time shares; over-adjustment possible.
- Mitigation: clamp proxy and keep fallback deterministic.

2. Data risk
- Some issuers/tickers may not provide both basic and diluted tags consistently.
- Mitigation: optional extraction + explicit fallback to S2.

3. Migration risk
- New base fields touch extraction and canonical contracts.
- Mitigation: optional-only additions; targeted regression tests.

4. Rollback
- Revert S3-lite policy block in `saas.py` to restore pure S2 behavior.
- Keep new extraction fields harmless if unused.

## Validation and Rollout Gates
1. Gate 1 (Unit/Contract)
- `ruff check` on changed files.
- Targeted pytest for parameter builder + graph guards.

2. Gate 2 (Behavior)
- Validate denominator trace for:
  - no market shares,
  - market shares lower than filing,
  - dilution proxy available/unavailable.

3. Gate 3 (Architecture compliance)
- Manual architecture-standard-enforcer review on changed modules:
  - no layer leakage,
  - strict typing preserved,
  - logging/assumption traceability preserved.

## Assumptions/Open Questions
1. Confirmed: S3-lite in this round uses dilution proxy only, no option fair-value model.
2. Confirmed: SEC + yfinance only for this round.
3. Assumed: proxy is applied only to DCF SaaS path (`dcf_growth` / `dcf_standard` via shared SaaS builder).
