# T36 Spec — Observability Summaries, Rollout Hygiene, Final Validation

## Goal
Close the enterprise technical data epic by adding a deterministic observability summary for report consumers and proving rollout hygiene with final validation.

## Scope
- Add additive `observability_summary` to the technical report contract.
- Build the summary from root-application projection artifacts.
- Surface it in frontend diagnostics.
- Run final validation and hygiene sweeps.

## Non-Goals
- No new compatibility shim
- No workflow-state contract expansion unless strictly required
- No new subdomain or topology changes

## Acceptance Criteria
- Technical full report exposes a typed `observability_summary`.
- Summary describes projection coverage / degraded artifact sources / observed timeframes without local consumer recomputation.
- Frontend diagnostics render the observability summary.
- Final backend/frontend validation passes.

## Validation
- `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_technical_application_use_cases.py finance-agent-core/tests/test_artifact_contract_registry.py finance-agent-core/tests/test_artifact_api_contract.py finance-agent-core/tests/test_workflow_state_contract_alignment.py finance-agent-core/tests/test_technical_interface_serializers.py -q`
- `uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical finance-agent-core/src/interface/artifacts finance-agent-core/tests/test_technical_application_use_cases.py finance-agent-core/tests/test_technical_interface_serializers.py`
- `npm --prefix frontend run test -- src/components/agent-outputs/technical-wording.test.ts src/components/agent-outputs/TechnicalAnalysisOutput.test.tsx src/types/agents/artifact-parsers.test.ts`
- `npm --prefix frontend run typecheck`
- `npm --prefix frontend run sync:api-contract`
