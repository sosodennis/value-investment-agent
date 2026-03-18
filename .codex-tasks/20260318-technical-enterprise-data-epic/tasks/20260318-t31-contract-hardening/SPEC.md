# Task Specification

## Goal
Harden the highest-value technical contract path by turning `feature_pack` indicator metadata and summary fields into typed enterprise-grade structures with provenance and quality semantics.

## In Scope
- `feature_pack` domain snapshot to artifact contract path
- `TechnicalFeatureIndicatorData` contract hardening
- `feature_summary` contract hardening
- backend serializer/payload conversion updates
- targeted backend contract and application tests

## Out of Scope
- normalized evidence bundle
- policy alerts
- frontend UI rendering changes
- broader timeseries/pattern/regime/fusion contract hardening beyond what is required for this slice

## Constraints
- no compatibility shims
- additive-safe migration where possible
- preserve existing root topology
- update at least one consumer/test in the same slice

## Acceptance Criteria
- `feature_pack` artifacts expose typed indicator provenance/quality fields instead of relying only on loose metadata
- `feature_summary` becomes a typed summary with readiness/quality semantics beyond raw counts
- feature compute use case and downstream readers/tests accept the new contract
- targeted pytest and ruff checks pass

## Validation
- `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_artifact_contract_registry.py finance-agent-core/tests/test_artifact_api_contract.py finance-agent-core/tests/test_technical_application_use_cases.py -q`
- `uv run --project finance-agent-core python -m ruff check finance-agent-core/src/interface/artifacts finance-agent-core/src/agents/technical/interface finance-agent-core/src/agents/technical/subdomains/features finance-agent-core/src/agents/technical/application/use_cases/run_feature_compute_use_case.py finance-agent-core/tests/test_artifact_contract_registry.py finance-agent-core/tests/test_artifact_api_contract.py`
