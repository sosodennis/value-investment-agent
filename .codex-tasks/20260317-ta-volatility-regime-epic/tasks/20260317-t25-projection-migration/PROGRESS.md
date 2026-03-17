# Progress Log

## Session Start
- **Date**: 2026-03-17
- **Task**: 20260317-t25-projection-migration
- **Goal**: Complete the output-contract migration so deterministic regime and VP-lite evidence reaches semantic/report consumers.

## Context Recovery Block
- **Current milestone**: None
- **Current status**: DONE
- **Current artifact**: `TODO.csv`
- **Key context**: Semantic/report consumers now load the regime pack and project deterministic regime plus structure summaries without introducing new subdomains or compatibility shims.
- **Next action**: Hand off to T26.

## Completion Summary
- **Status**: DONE
- **Completed**: 2026-03-17 22:55
- **What was done**:
  - Extended semantic pipeline contracts to load `regime_pack` and centralized projection-context assembly in the application layer.
  - Added deterministic `regime_summary`, `volume_profile_summary`, and `structure_confluence_summary` to interpretation setup context and full-report payloads.
  - Updated full-report/backend canonical contract plus frontend parser/types so the new summary fields and `regime_pack_id` are consumer-visible.
- **Validation**:
  - `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_application_use_cases.py finance-agent-core/tests/test_technical_interface_serializers.py -q` -> 19 passed
  - `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_artifact_api_contract.py -q` -> 3 passed
  - `uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical/application/semantic_interpretation_input_service.py finance-agent-core/src/agents/technical/application/semantic_pipeline_contracts.py finance-agent-core/src/agents/technical/application/semantic_pipeline_service.py finance-agent-core/src/agents/technical/interface/contracts.py finance-agent-core/src/agents/technical/interface/serializers.py finance-agent-core/tests/test_technical_application_use_cases.py finance-agent-core/tests/test_technical_interface_serializers.py` -> exit 0
  - `cd frontend && npm test -- --run src/types/agents/artifact-parsers.test.ts` -> 20 passed
- **Compliance**:
  - No `interface -> application` imports were introduced.
  - No deep `subdomains.(patterns|regime).domain` imports leaked into application/interface consumers.
  - Projection logic stayed in application/interface owners; no new domain policy drift was introduced.
- **Notes**:
  - Exploratory `finance-agent-core/tests/test_output_contract_serializers.py` still fails on a legacy non-canonical technical artifact payload expectation and was not used as this slice gate.
