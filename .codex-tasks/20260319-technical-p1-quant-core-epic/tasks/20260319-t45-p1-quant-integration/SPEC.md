# Task Specification

## Task Shape
- **Shape**: `single-full`

## Goals
- Integrate the four `P1 core` quant families into evidence/readout surfaces.
- Ensure backend/frontend contracts stay synchronized.
- Close rollout hygiene and validation for the epic.

## Non-Goals
- Do not start `P1.5` families.
- Do not start the full calibration program in this task.

## Constraints
- Must consume the completed P1 quant families instead of inventing temporary local readouts.
- Must preserve deterministic backend ownership of numeric logic.
- Must keep frontend as consumer of backend-owned summaries, not local re-deriver.

## Deliverables
- Evidence/readout integration for the new quant families.
- Contract and parser alignment if needed.
- Final validation and rollout notes.

## Done-When
- [ ] New P1 quant families appear in evidence/readout surfaces where appropriate
- [ ] Backend/frontend validation passes

## Final Validation Command
```bash
uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_application_use_cases.py finance-agent-core/tests/test_technical_interface_serializers.py finance-agent-core/tests/test_artifact_api_contract.py -q && uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical finance-agent-core/src/interface/artifacts finance-agent-core/tests/test_technical_application_use_cases.py finance-agent-core/tests/test_technical_interface_serializers.py && npm --prefix frontend run test -- src/types/agents/artifact-parsers.test.ts src/components/agent-outputs/TechnicalAnalysisOutput.test.tsx && npm --prefix frontend run typecheck
```
