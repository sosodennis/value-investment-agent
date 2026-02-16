# Agent Layer Responsibility and Naming Guideline
Date: 2026-02-13
Scope: `finance-agent-core/src/agents/*`
Policy: Zero compatibility, fail-fast, contract-first.

This document is normative for backend agent package design.

## 1. Standard Agent Package Shape

Each agent package should follow:

```text
src/agents/<agent_name>/
  domain/
  application/
  data/
  interface/
```

`src/workflow/**` is framework orchestration only and must stay thin.

## 2. Layer Responsibilities

### Domain
Owns business semantics and rules.

Allowed:
1. Invariants, thresholds, scoring rules, valuation logic.
2. Domain entities/value objects.
3. Pure domain services and policies.

Forbidden:
1. Artifact envelope/API DTO assembly.
2. Persistence/network/LLM I/O.
3. LangGraph/FastAPI framework wiring.

### Application
Owns use-case orchestration for one agent.

Allowed:
1. Workflow-facing orchestration (`*Orchestrator`, `use_cases`).
2. Calls domain rules and data ports.
3. Builds command/update payloads for workflow transitions.

Forbidden:
1. Domain decision rules that belong in `domain`.
2. Direct low-level external clients (must go through data layer).

### Data
Owns I/O adapters and persistence implementations.

Allowed:
1. `*Port` implementations for artifacts/repositories.
2. External clients (`sec`, `search`, `market data`, etc.).
3. Serialization for storage transport shape.

Forbidden:
1. Business scoring/decision logic.
2. UI/API contract mapping.

### Interface
Owns boundary contracts and shape adaptation.

Allowed:
1. Pydantic contract models for agent public artifacts.
2. Parsers/serializers/mappers/formatters.
3. Prompt templates and user-facing textual schemas.

Forbidden:
1. Domain policy/decision logic.
2. Storage/network side-effects.

## 3. Dependency Rules (Mandatory)

1. `domain` imports:
   - same-agent `domain`
   - `src/shared/kernel/**`
   - never from `application/data/interface/workflow`
2. `application` imports:
   - same-agent `domain`
   - same-agent `data` (ports)
   - same-agent `interface` (mappers/contracts only when boundary-required)
   - never from `workflow`
3. `data` imports:
   - same-agent `data`
   - same-agent `interface` contracts (for typed validation)
   - `src/shared/**`, `src/services/**` infra adapters
   - never from `workflow`
4. `interface` imports:
   - same-agent `application` view models (read-only mapping use)
   - same-agent `domain` only for type-safe serialization/parsing
   - never from `workflow`
5. `workflow` imports:
   - `src/agents/<agent>/application/**` as primary entrypoints
   - may reference agent interface constants/contracts only for node wiring
   - must not own domain rules or external I/O policies

## 4. Naming Conventions (Mandatory)

### Files
1. `domain/models.py`: domain entities/value objects.
2. `domain/services.py`: pure business rules.
3. `domain/policies.py`: thresholds/quotas/selection policies.
4. `application/orchestrator.py`: workflow-facing orchestration.
5. `application/use_cases.py`: reusable application flows.
6. `application/view_models.py`: UI-facing intermediate view state.
7. `data/ports.py`: typed port adapters.
8. `data/clients/*.py`: external provider clients.
9. `interface/contracts.py`: Pydantic public artifact models.
10. `interface/mappers.py`: `summarize_<agent>_for_preview(...)`.
11. `interface/formatters.py`: display formatting only.
12. `interface/prompts.py`: LLM prompts (if agent-specific).

Avoid generic names like `structures.py` in new code.
Prefer explicit role names: `contracts.py`, `models.py`, `policies.py`.

### Class and Function Suffixes
1. `*Orchestrator`: application orchestration class.
2. `*Port`: data port class.
3. `*Client`: external client adapter.
4. `*Model`: interface contract model (Pydantic).
5. `*Result`: use-case/domain result dataclass.
6. `parse_*`: strict boundary parse/validation.
7. `build_*_payload`: boundary payload assembly.
8. `summarize_*_for_preview`: preview mapper entrypoint.

## 5. Placement Decision Checklist

Before adding a new class/function, answer:

1. Is this a business rule independent of I/O? -> `domain`.
2. Is this sequencing multiple steps/use-cases? -> `application`.
3. Is this reading/writing artifacts or external APIs? -> `data`.
4. Is this shape validation/serialization/mapping for boundaries? -> `interface`.
5. Is this LangGraph node wiring only? -> `workflow`.

If unclear, do not place into `workflow` by default.
Resolve by this document first, then place.

## 6. Definition of Done for Agent Refactor

1. `workflow` node is thin (no domain policy logic).
2. Agent has non-empty `domain` with meaningful business rules.
3. External tool logic sits under `data/clients`.
4. Public artifact contracts live in `interface/contracts.py`.
5. Tests cover at least:
   - domain services
   - application orchestration/use-cases
   - interface parser/mapper
   - data port behavior
