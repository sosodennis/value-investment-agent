# Task Specification

## Task Shape
- **Shape**: `single-full`

## Goals
- Add normalized-distance quant features using free-data-compatible OHLCV inputs.
- Expose the features through technical artifacts in an evidence-friendly deterministic contract.
- Keep the features suitable for later alert/readout integration.

## Non-Goals
- Do not mix this task with persistence or structural-break work.
- Do not redesign frontend wording in this task.

## Constraints
- Must preserve hardened technical contracts.
- Must keep runtime logic deterministic and backend-owned.
- Must avoid introducing new paid-data assumptions.

## Deliverables
- Normalized-distance feature implementation.
- Contract/test updates.
- Validation notes.

## Done-When
- [ ] Normalized-distance features are computed and surfaced through technical artifacts
- [ ] Targeted tests and lint pass

## Final Validation Command
```bash
uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_application_use_cases.py -q -k "feature or momentum or distance" && uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical/subdomains/features finance-agent-core/src/agents/technical/application/use_cases/run_feature_compute_use_case.py finance-agent-core/src/agents/technical/interface finance-agent-core/tests/test_technical_application_use_cases.py
```
