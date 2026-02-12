# Backend Development Guidelines

This document defines the required development rules after the no-compatibility refactor.

## 1. Core Principles

1. No compatibility branches in core logic.
2. No duck typing in core logic (`hasattr`, shape guessing).
3. No `Any` in `src/` and `api/`.
4. Boundary strict, core deterministic.

## 2. Boundary vs Core

Boundary layers:
1. FastAPI request/response handlers (`api/server.py`)
2. LangGraph event adapter (`src/interface/adapters.py`)
3. Persistence serialization (`src/services/history.py`, DB artifact I/O)
4. Interrupt payload ingestion

Core layers:
1. Workflow state (`src/workflow/state.py`)
2. Workflow nodes (`src/workflow/nodes/**`)
3. Output mapping (`src/interface/mappers.py`)

Rule:
1. Validate/normalize at boundary.
2. Use only canonical typed shapes in core.

## 3. Canonical Payload Rules

Use shared types in `src/common/types.py`:
1. `JSONValue`
2. `JSONObject`
3. `ArtifactReferencePayload`
4. `AgentOutputArtifactPayload`

State `artifact` fields must store canonical dict payloads, not Pydantic objects.

Use:
1. `build_artifact_payload(...)` for agent output artifacts.

Do not:
1. Assign `AgentOutputArtifact(...)` directly into state.

## 4. Type Rules

1. All function signatures require explicit types.
2. Prefer `TypedDict`, `Literal`, `BaseModel`, and small aliases.
3. If you need flexible JSON payloads, use `JSONValue` / `JSONObject` from `src/common/types.py`.

Forbidden:
1. `Any` (in `src/` and `api/`)
2. `hasattr(...)`-driven type dispatch in core

## 5. Import Rules for Provenance

`ComputedProvenance`, `ManualProvenance`, `XBRLProvenance`, `TraceableField` must be imported from:

1. `src/common/traceable.py`

Do not import these via `sec_xbrl/models.py` re-export assumptions.

## 6. Testing and Validation Checklist

Before opening a PR:

1. Lint touched files:
```bash
cd finance-agent-core
uv run ruff check <touched-files>
```

2. Ensure forbidden patterns are absent:
```bash
rg -n "\bAny\b|hasattr\(" src api
```

3. Run critical interface tests:
```bash
uv run pytest tests/test_protocol.py tests/test_mappers.py tests/test_news_mapper.py tests/test_debate_mapper.py -q
```

## 7. Change Pattern (Recommended)

When adding a new agent output field:

1. Update canonical types (if needed) in `src/common/types.py`.
2. Update state `TypedDict` contract in `src/workflow/state.py`.
3. Produce payload via `build_artifact_payload(...)`.
4. Keep `NodeOutputMapper` contract stable (artifact remains canonical dict).
5. Add/adjust tests for adapter + mapper behavior.

## 8. Anti-Patterns

1. Writing fallback branches for old payload shapes.
2. Mixing Pydantic models and dict payloads in state.
3. Silent coercion of unknown object types in history/event serialization.
4. Re-introducing `Any` to speed up implementation.
