# Backend Guideline
Date: 2026-02-12
Scope: `finance-agent-core`
Policy: Zero compatibility in workflow contract path.

## 1. Backend Architecture Boundaries

1. Domain: business semantics, invariants, financial rules (`src/agents/*/domain/**`).
2. Application: agent use-cases and orchestrators (`src/agents/*/application/**`).
3. Data: repositories/adapters to persistence and providers (`src/agents/*/data/**`).
4. Interface: contracts/parsers/serializers/mappers (`src/agents/*/interface/**`, `src/interface/**`).
5. Orchestration: framework wiring/state transitions (`src/workflow/**`).
6. Infrastructure: DB/runtime/external integrations (`src/infrastructure/**`, external services).

Rule:
1. Workflow nodes are orchestration-only and call agent application entrypoints.
2. Contract validation happens at boundaries (interface/ports), not ad-hoc in nodes.
3. Domain logic must not live in `src/workflow/**`.
4. Example end-state entrypoint:
   - `src/agents/fundamental/application/orchestrator.py`

## 2. Mandatory Contract Path

For artifacts:
1. Canonicalize payload with `src/interface/canonical_serializers.py` when needed.
2. Artifact kind -> model routing must go through `src/interface/artifact_contract_registry.py`.
3. Persist/read via per-agent ports (`src/agents/*/data/ports.py`) using shared `TypedArtifactPort[TModel]` from `src/shared/data/typed_artifact_port.py`.
4. Store envelope via `src/services/artifact_manager.py`.

For agent output:
1. Build with `build_artifact_payload(...)` from `src/interface/schemas.py`.
2. Output must include `kind/version/summary/preview/reference`.

Constants:
1. Use `src/common/contracts.py` for artifact kinds/output kinds/version constants.
2. Do not hardcode contract literal strings in new logic.

## 3. Workflow Node Rules

1. No direct `artifact_manager.get_artifact_data(...)` in workflow nodes.
2. No legacy fallback to old mirror state IDs for cross-agent consumption.
3. No `resolved_ticker -> state.ticker` compatibility fallback in core decision paths.
4. Missing required contract field should fail fast with explicit error.

## 4. Type Rules

1. No `Any` in `src/` and `api/` runtime path.
2. No `hasattr(...)`-based dispatch in core path.
3. Prefer `TypedDict`, `Literal`, Pydantic `BaseModel`, and `JSONValue/JSONObject` aliases.
4. Provenance imports must come from `src/common/traceable.py`.

## 5. Canonical Backend File Map

1. Contract constants: `src/common/contracts.py`
2. Shared JSON types: `src/common/types.py`
3. Output schema: `src/interface/schemas.py`
4. Artifact API schema: `src/interface/artifact_api_models.py`
5. Contract registry (kind routing): `src/interface/artifact_contract_registry.py`
   Includes debate/news/technical consumption policies for cross-agent payload reads.
6. Canonicalization: `src/interface/canonical_serializers.py`, `src/agents/*/interface/contracts.py`, `src/interface/artifact_model_shared.py`
7. Domain ports:
   - Shared generic port: `src/shared/data/typed_artifact_port.py`
   - Per-agent concrete ports: `src/agents/*/data/ports.py`

## 6. Standard Backend Change Recipes

## 6.1 Add New Agent Artifact/Output

1. Add kind constants in `src/common/contracts.py`.
2. Add/extend interface schemas (`schemas.py`, `artifact_api_models.py`).
3. Add typed save/load methods in domain artifact port.
4. Use typed port methods in node.
5. Add/adjust tests and fixtures.

## 6.2 Remove Field/Class/Output

1. Remove producer and consumer in same PR.
2. Remove schema and parser branches in same PR.
3. Do not keep compatibility branch.
4. Update fixtures/tests in same PR.

## 7. Backend Quality Gates

1. `uv run --project finance-agent-core python -m ruff check <touched-files>`
2. `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_protocol.py finance-agent-core/tests/test_mappers.py finance-agent-core/tests/test_news_mapper.py finance-agent-core/tests/test_debate_mapper.py -q`
3. If contract/artifact changed, run:
   - `finance-agent-core/tests/test_artifact_api_contract.py`
   - `finance-agent-core/tests/test_error_handling_fundamental.py`
   - `finance-agent-core/tests/test_error_handling_news.py`
   - `finance-agent-core/tests/test_error_handling_technical.py`
   - `finance-agent-core/tests/test_param_builder_canonical_reports.py`

## 8. Backend Anti-Patterns

1. Writing fallback branches for old payload shape.
2. Mixing Pydantic model objects and unvalidated dicts in workflow state.
3. Silent coercion to hide contract drift.
4. Reintroducing direct artifact manager reads in node code.

## 9. Detailed Reference

1. `docs/backend-canonicalization-flow.md` (detailed canonicalization and artifact flow)
2. `docs/fundamental-reference-architecture.md` (concrete package-boundary example)
