# Task Specification

## Task Shape
- **Shape**: `single-full`

## Goals
- Add liquidity-proxy quant features using free-data-compatible OHLCV plus volume inputs.
- Surface those features through technical artifacts with deterministic quality semantics.
- Keep the features explainable and suitable for later evidence/readout integration.

## Non-Goals
- Do not implement order-book or microstructure-only liquidity metrics.
- Do not depend on premium market data.

## Constraints
- Must stay compatible with current free-data assumptions.
- Must preserve technical interface ownership and existing contract hardening.
- Must avoid frontend-local derivation requirements.

## Deliverables
- Liquidity-proxy feature implementation.
- Contract/test updates.
- Validation notes.

## Done-When
- [ ] Liquidity-proxy features are computed and surfaced through technical artifacts
- [ ] Targeted tests and lint pass

## Final Validation Command
```bash
uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_application_use_cases.py -q -k "feature or liquidity" && uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical/subdomains/features finance-agent-core/src/agents/technical/application/use_cases/run_feature_compute_use_case.py finance-agent-core/src/agents/technical/interface finance-agent-core/tests/test_technical_application_use_cases.py
```
