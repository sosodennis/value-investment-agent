# Progress Log

## Session Start
- **Date**: 2026-03-18
- **Task**: 20260318-t32-evidence-layer
- **Goal**: Build a normalized deterministic evidence layer and migrate semantic projection/setup consumers onto it.

## Context Recovery Block
- **Current step**: COMPLETE
- **Current status**: DONE
- **Current artifact**: `TODO.csv`
- **Key context**:
  - `T31` is complete, so feature/pattern/regime/fusion inputs now have typed contracts.
  - `Slice 1` built the reusable evidence bundle and migrated semantic setup/projection consumers.
  - `Slice 2` externalized that bundle into full report serialization and frontend parser/type consumers.
- **Next action**: hand off to the next epic child now that `T32` is complete.

## Slice 1 Complete: Internal evidence bundle and semantic reuse
- **Completed**: 2026-03-18 15:00
- **Outcome**:
  - Added a normalized `TechnicalEvidenceBundle` to projection artifacts in root `application`.
  - Added `technical_evidence_bundle_service.py` to assemble deterministic evidence once from typed feature/pattern/regime/fusion/scorecard artifacts.
  - Migrated semantic setup context and projection context to reuse the same bundle instead of independently re-deriving summaries.
- **Validation**:
  - `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_application_use_cases.py finance-agent-core/tests/test_workflow_state_contract_alignment.py -q` -> `27 passed`
  - `uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical/application/semantic_pipeline_contracts.py finance-agent-core/src/agents/technical/application/technical_evidence_bundle_service.py finance-agent-core/src/agents/technical/application/semantic_interpretation_input_service.py finance-agent-core/src/agents/technical/application/semantic_pipeline_service.py finance-agent-core/tests/test_technical_application_use_cases.py` -> `All checks passed`

## Slice 2 Complete: Full-report and frontend consumer promotion
- **Completed**: 2026-03-18 15:14
- **Outcome**:
  - Added a typed `evidence_bundle` field to the technical full-report boundary contract.
  - Promoted normalized evidence into the full report serialization path by projecting the shared application evidence bundle directly into final report payloads.
  - Aligned frontend technical report types, parser coverage, and generated API contract so at least one downstream non-semantic consumer path now reads normalized evidence without local re-derivation.
- **Validation**:
  - `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_application_use_cases.py finance-agent-core/tests/test_technical_interface_serializers.py finance-agent-core/tests/test_artifact_api_contract.py -q` -> `31 passed`
  - `uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical/application/technical_evidence_bundle_service.py finance-agent-core/src/agents/technical/application/semantic_pipeline_service.py finance-agent-core/src/agents/technical/interface/contracts.py finance-agent-core/src/agents/technical/interface/serializers.py finance-agent-core/tests/test_technical_application_use_cases.py finance-agent-core/tests/test_technical_interface_serializers.py` -> `All checks passed`
  - `npm --prefix frontend run test -- src/types/agents/artifact-parsers.test.ts` -> `20 passed`
  - `npm --prefix frontend run typecheck` -> passed
  - `npm --prefix frontend run sync:api-contract` -> passed
