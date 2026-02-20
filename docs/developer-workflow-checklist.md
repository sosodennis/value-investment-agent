# Developer Workflow Checklist
Date: 2026-02-16
Scope: `finance-agent-core`
Policy: Simple Triad + strict typed boundary + strict naming.

This checklist is mandatory for agent refactor and boundary-sensitive changes.

## 1. Pre-Change Checklist

1. Confirm the target layer for each change:
   - domain rule -> `domain/`
   - use-case orchestration -> `application/`
   - external/storage adapter -> `data/`
   - contract mapping/DTO serialization -> `interface/`
2. Confirm boundary direction:
   - Domain/Application internal path: typed model/domain object only.
   - Cross-agent/workflow/artifact/API path: JSON DTO (`dict`/`list[dict]`) only.
3. Define one explicit conversion point:
   - model -> DTO or DTO -> model conversion can happen only once at adapter boundary.

## 2. Boundary Change Checklist

1. Do not put mapping/serialization in `src/workflow/nodes/**`.
2. If cross-agent contract changed:
   - update `interface/contracts.py` and parser/serializer together.
   - update producer and consumer in the same PR.
3. For incident-prone boundaries, log with unified schema:
   - required keys: `node`, `artifact_id`, `contract_kind`, `error_code`
   - include `replay` diagnostics snapshot.
4. For workflow node `Command` assembly:
   - use `src/workflow/command_adapter.py` (no duplicated per-node `goto == "END"` conversion)
   - use `src/shared/kernel/workflow_routing.py` for END sentinel normalization

## 3. Incident 5-Minute Triage

1. Filter logs by `BOUNDARY_EVENT`.
2. Locate first non-`OK` `error_code`.
3. Read `contract_kind` to classify fault:
   - `workflow_state`
   - `interrupt_payload`
   - `artifact_json`
   (canonical kind/source: `src/shared/kernel/boundary_contracts.py`)
4. Use `replay.artifact_refs` and `replay.current_node` to replay the failing boundary input.
5. Verify whether failure is:
   - model/dict mixed flow
   - missing required contract field
   - incorrect boundary conversion location

## 4. PR Validation Gates

1. Lint touched files:
   - `uv run --project finance-agent-core python -m ruff check <touched-files>`
2. Run targeted tests for touched agents and boundary contracts.
3. If boundary behavior changed, include at least:
   - one success-case serializer/mapper test
   - one failure-case boundary regression test

## 5. Naming and API Surface

1. Prefer direct module imports over package-level facade imports.
2. Keep `__init__.py` surface minimal:
   - only canonical entrypoints should be re-exported.
   - remove dead re-export symbols.
3. New logic file names must stay role-explicit:
   - `*_service.py`, `orchestrator.py`, `state_readers.py`, `state_updates.py`
   - `serializers.py`, `parsers.py`, `mappers.py`, `prompt_renderers.py`
