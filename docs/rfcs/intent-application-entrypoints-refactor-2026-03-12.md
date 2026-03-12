# Intent Application Entrypoints Refactor (2026-03-12)

## Requirement Breakdown
- Align `src/agents/intent` with the same enterprise topology used in `fundamental`.
- Move orchestration entrypoints (`subgraph.py`, `wiring.py`) into `application/`.
- Remove root-level entrypoints with no compatibility shims.
- Keep runtime behavior unchanged.

## Technical Objectives and Strategy
- Keep `application/` as the owner for orchestration and wiring.
- Keep `domain/`, `interface/`, and `infrastructure/` unchanged.
- Avoid subdomain splits (criteria not met).

## Involved Files
- `finance-agent-core/src/agents/intent/subgraph.py`
- `finance-agent-core/src/agents/intent/wiring.py`
- `finance-agent-core/src/agents/intent/application/subgraph.py` (new)
- `finance-agent-core/src/agents/intent/application/wiring.py` (new)
- `finance-agent-core/src/workflow/graph.py`
- `finance-agent-core/src/workflow/nodes/intent_extraction/nodes.py`
- `finance-agent-core/tests/test_agent_subgraph_entrypoints.py`

## Detailed Per-File Plan

### Slice 1 (small): Move Entry Points Into Application
Objective:
- Move `subgraph.py` and `wiring.py` into `application/`.
- Update all imports to new paths.
- Remove old root-level files.

Changes:
- `src/agents/intent/subgraph.py` → `src/agents/intent/application/subgraph.py`
- `src/agents/intent/wiring.py` → `src/agents/intent/application/wiring.py`
- Update imports in:
  - `src/workflow/graph.py`
  - `src/workflow/nodes/intent_extraction/nodes.py`
  - `tests/test_agent_subgraph_entrypoints.py`

Validation:
- `rg "agents.intent.subgraph|agents.intent.wiring" finance-agent-core -g"*.py"`
- `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_agent_subgraph_entrypoints.py -q`

## Old → New Mapping
- `src/agents/intent/subgraph.py` → `src/agents/intent/application/subgraph.py`
- `src/agents/intent/wiring.py` → `src/agents/intent/application/wiring.py`

## Risk/Dependency Assessment
- Low risk: import path updates only.
- Failure mode: import errors if any call sites remain on old paths.

## Validation and Rollout Gates
- Legacy path sweep: `rg "agents.intent.subgraph|agents.intent.wiring" ...`
- Targeted test: `tests/test_agent_subgraph_entrypoints.py`

## Assumptions/Open Questions
- No external (non-repo) consumers depend on old root-level paths.
- No compatibility shims are allowed.
