# Task Specification

## Task Shape
- **Shape**: `single-full`

## Goals
- Add volatility-regime quant features using free-data-compatible OHLCV inputs.
- Surface those features through technical artifacts with deterministic quality semantics.
- Prepare the features for later evidence/readout integration without coupling them to frontend wording.

## Non-Goals
- Do not implement options, macro, or premium-data volatility features.
- Do not redesign fusion scoring wholesale.

## Constraints
- Must stay free-data-compatible.
- Must preserve technical contract hardening and interface ownership rules.
- Must not reintroduce loose `dict[str, object]` payload assembly into `application`.

## Deliverables
- Volatility-regime feature implementation.
- Technical contract updates if needed.
- Regression tests and validation notes.

## Done-When
- [ ] Volatility-regime quant features are computed and serialized through the hardened technical surface
- [ ] Targeted tests and lint pass

## Final Validation Command
```bash
uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_application_use_cases.py -q -k "feature or regime or volatility" && uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical/subdomains/features finance-agent-core/src/agents/technical/application/use_cases/run_feature_compute_use_case.py finance-agent-core/src/agents/technical/interface finance-agent-core/tests/test_technical_application_use_cases.py
```
