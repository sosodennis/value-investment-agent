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
1. Canonicalize payload with agent interface parser (`src/agents/*/interface/contracts.py`) when needed.
2. Artifact kind -> model routing must go through `src/interface/artifacts/artifact_contract_registry.py`.
3. Persist/read via per-agent ports (`src/agents/*/data/ports.py`) using shared `TypedArtifactPort[TModel]` from `src/shared/cross_agent/data/typed_artifact_port.py`.
4. Store envelope via `src/services/artifact_manager.py`.

For agent output:
1. Build with `build_artifact_payload(...)` from `src/interface/events/schemas.py`.
2. Output must include `kind/version/summary/preview/reference`.

Constants:
1. Use `src/shared/kernel/contracts.py` for artifact kinds/output kinds/version constants.
2. Do not hardcode contract literal strings in new logic.

For workflow state / interrupt payloads:
1. Domain objects must be converted through `src/agents/*/interface/{mappers,serializers}.py` before entering workflow state or interrupt payloads.
2. Workflow nodes must not call `model_dump()` / `model_validate()` directly on domain entities/value objects.
3. If a node needs JSON-ready payload, it should call an application entrypoint that internally uses interface serializers.

## 3. Workflow Node Rules

1. No direct `artifact_manager.get_artifact_data(...)` in workflow nodes.
2. No legacy fallback to old mirror state IDs for cross-agent consumption.
3. No `resolved_ticker -> state.ticker` compatibility fallback in core decision paths.
4. Missing required contract field should fail fast with explicit error.
5. No domain-to-DTO mapping logic inline in nodes; place in interface serializers/mappers and invoke via application orchestration.

## 4. Type Rules

1. No `Any` in `src/` and `api/` runtime path.
2. No `hasattr(...)`-based dispatch in core path.
3. Prefer `TypedDict`, `Literal`, Pydantic `BaseModel`, and `JSONValue/JSONObject` aliases.
4. Provenance imports must come from `src/shared/kernel/traceable.py`.

## 5. Canonical Backend File Map

1. Contract constants: `src/shared/kernel/contracts.py`
2. Shared JSON types: `src/shared/kernel/types.py`
3. Output schema: `src/interface/events/schemas.py`
4. Artifact API schema: `src/interface/artifacts/artifact_api_models.py`
5. Contract specs SSOT (kind->model): `src/interface/artifacts/artifact_contract_specs.py`
6. Contract registry (kind routing): `src/interface/artifacts/artifact_contract_registry.py`
   Includes debate/news/technical consumption policies for cross-agent payload reads.
7. Canonicalization: `src/agents/*/interface/contracts.py`, `src/interface/artifacts/artifact_contract_registry.py`, `src/interface/artifacts/artifact_model_shared.py`
8. Domain ports:
   - Shared generic port: `src/shared/cross_agent/data/typed_artifact_port.py`
   - Per-agent concrete ports: `src/agents/*/data/ports.py`

## 6. Standard Backend Change Recipes

## 6.1 Add New Agent Artifact/Output

1. Add kind constants in `src/shared/kernel/contracts.py`.
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
5. `application/use_cases.py` 作為純 re-export 聚合層（易造成命名/責任混亂）。

## 8. Typed Artifact Port Policy (Mandatory)

1. Shared generic data contract path is `src/shared/cross_agent/data/typed_artifact_port.py`.
2. Per-agent `data/ports.py` may keep thin facades only when they provide one of:
   - domain naming clarity for use-cases
   - multi-artifact composition helper
   - domain projection helper (entity mapping)
3. Repetitive pure forwarding logic must be consolidated via internal generic helpers (no copy-paste save/load bodies).
4. Do not bypass per-agent ports from workflow nodes; workflow uses application/data entrypoints only.
5. If a facade method is pure pass-through and adds no naming/composition meaning, remove it or merge it into a higher-level helper.

## 9. Application Naming Rules (Mandatory)

1. `orchestrator.py`: 只做流程編排與節點轉移。
2. `*_service.py`: 單一業務流程片段（可測、可重用）。
3. `state_readers.py`: 只做 state extraction / typed read。
4. `state_updates.py`: 只做 state update payload 組裝。
5. `dto.py`: application layer DTO。
6. `ports.py`: application 對外依賴介面。
7. 禁止新增 `use_cases.py` 作為 alias/re-export facade；若已有歷史檔案，應逐步刪除並改為直接引用 service/state modules。

## 10. Detailed Reference

1. `docs/backend-canonicalization-flow.md` (detailed canonicalization and artifact flow)
2. `docs/agent-layer-responsibility-and-naming-guideline.md` (authoritative agent-layer ownership + naming)
3. `docs/simple-triad-layer-alignment-2026-02-16.md` (strict boundary and incident alignment note)
4. `docs/next-refactor-pending-2026-02-16.md` (current refactor backlog)
5. `docs/developer-workflow-checklist.md` (developer execution checklist and incident triage)

## 11. Boundary Observability Policy (Mandatory)

1. Incident-prone boundary nodes must emit unified logs with these keys:
   - `node`
   - `artifact_id`
   - `contract_kind`
   - `error_code`
2. Use shared helper `src/shared/kernel/tools/incident_logging.py` for consistency.
3. Non-`OK` boundary events must include replay diagnostics snapshot (`replay`) so incidents can be localized quickly.
