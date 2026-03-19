# Task Specification

## Task Shape
- **Shape**: `single-full`

## Goals
- Add cross-timeframe-alignment quant features using existing multi-timeframe technical inputs.
- Surface alignment/disagreement semantics through deterministic technical contracts.
- Prepare these features for later evidence/readout integration without frontend-local logic.

## Non-Goals
- Do not broaden this task into macro alignment or premium-data breadth.
- Do not rebuild the entire fusion engine.

## Constraints
- Must use existing free-data-compatible timeframe inputs.
- Must preserve technical interface ownership and recent boundary hardening.
- Must remain deterministic and backend-owned.

## Deliverables
- Cross-timeframe-alignment feature implementation.
- Contract/test updates.
- Validation notes.

## Done-When
- [ ] Cross-timeframe alignment features are computed and surfaced through technical artifacts
- [ ] Targeted tests and lint pass

## Final Validation Command
```bash
uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_application_use_cases.py -q -k "feature or fusion or alignment" && uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical/subdomains/features finance-agent-core/src/agents/technical/application/use_cases/run_feature_compute_use_case.py finance-agent-core/src/agents/technical/application/use_cases/run_fusion_compute_use_case.py finance-agent-core/src/agents/technical/interface finance-agent-core/tests/test_technical_application_use_cases.py
```
