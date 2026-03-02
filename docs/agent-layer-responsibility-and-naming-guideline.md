# Agent Layer Responsibility and Naming Guideline
Date: 2026-02-27
Scope: `finance-agent-core/src/agents/*`
Policy: Zero compatibility, fail-fast, contract-first.
Enforcement: Document-first mandatory constraints. No extra auto-lint naming rule is required in this phase.

This document is normative for backend agent package design and cross-agent naming consistency.

## 1. Purpose

1. Keep class/file naming consistent across `fundamental/news/debate/technical/intent`.
2. Prevent mixed responsibilities and hidden coupling.
3. Provide a reusable standard for future agent refactors.

## 2. Standard Agent Package Shape

Target shape:

```text
src/agents/<agent_name>/
  domain/
  application/
    ports/
    services/
    use_cases/
  interface/
  infrastructure/        # target end-state
  data/                  # legacy transition package
```

Notes:

1. `data/` is legacy for transition only; new concrete adapters should move to `infrastructure/`.
2. Do not create duplicated path segments like `application/fundamental`.
3. `src/workflow/**` is framework orchestration only and must stay thin.

## 3. Layer Responsibilities

### Domain

Allowed:

1. Invariants, thresholds, scoring rules, valuation logic.
2. Domain entities/value objects.
3. Pure domain services, policies, deterministic calculators.

Forbidden:

1. Artifact envelope/API DTO assembly.
2. Persistence/network/LLM I/O.
3. LangGraph/FastAPI framework wiring.
4. Runtime env/config reads.

### Application

Allowed:

1. Workflow-facing orchestration (`*Orchestrator`, `*_service`, `run_*` use-cases).
2. Calls domain + abstract ports.
3. Composes results for interface serialization.

Forbidden:

1. Domain decision rules that belong in `domain`.
2. Direct imports of concrete external clients/providers.
3. Transport parsing or storage-specific implementation details.

### Interface

Allowed:

1. Pydantic contract models for agent public artifacts.
2. Parsers/serializers/mappers/formatters.
3. Prompt templates and user-facing textual schemas.

Forbidden:

1. Domain policy/decision logic.
2. Storage/network side-effects.

### Infrastructure (Priority)

Allowed:

1. External provider integrations (SEC, market data, search, model APIs).
2. Artifact repositories and storage gateways.
3. Runtime config providers and infra policies.

Forbidden:

1. Workflow state-machine orchestration.
2. Business policy decisions that belong to domain.
3. Import-time side effects (registration/identity/env mutation).

## 4. Dependency Rules (Mandatory)

1. `domain` imports:
   - same-agent `domain`
   - `src/shared/kernel/**`
   - never from `application/interface/infrastructure/workflow`
2. `application` imports:
   - same-agent `domain`
   - same-agent `application/ports` or abstract contracts
   - same-agent `interface` only for boundary-required mapping/contracts
   - never from concrete infrastructure implementation
3. `interface` imports:
   - same-agent public application/domain types only
   - never from workflow/concrete infrastructure clients
4. `infrastructure` imports:
   - same-agent infrastructure internals
   - same-agent application ports
   - shared kernel/services infra utilities
   - never drives workflow routing logic
5. `workflow` imports:
   - `src/agents/<agent>/application/**` as entrypoints
   - may reference interface constants/contracts for wiring only
   - must not own domain rules or external I/O policy.

## 5. Naming Conventions (Mandatory)

### 5.1 File Naming

1. Use `snake_case.py`, noun-first, role-explicit.
2. Main file role must match main class role:
   - `*_service.py` -> `*Service`
   - `*_provider.py` -> `*Provider`
   - `*_repository.py` -> `*Repository`
   - `*_client.py` -> `*Client`
   - `*_factory.py` -> `*Factory`
   - `*_mapper.py` -> `*Mapper`
   - `*_policy.py` -> `*Policy`
3. Avoid generic new files: `tools.py`, `helpers.py`, `structures.py`.
4. `ports.py` should contain only protocols/abstract ports.

### 5.2 Class Suffix Semantics

1. `*Provider`: single upstream source adapter only.
2. `*Service`: orchestration/aggregation across components.
3. `*Repository`: persistence read/write gateway.
4. `*Client`: low-level transport or SDK wrapper.
5. `*Factory`: object assembly only.
6. `*Mapper`: shape conversion only.
7. `*Policy`: rules/config policy, no orchestration.
8. `*Port`: abstract protocol/interface only, never concrete implementation.
9. `*Orchestrator`: workflow-facing application orchestration only.

### 5.3 Acronym and Case Rules

1. Class names use `PascalCase`.
2. Acronym style must be consistent within one module family.
3. Preferred style: treat acronym as normal word (`Sec`, `Xbrl`, `Finbert`, `Fred`).
4. Do not mix styles like `SECFetchPolicy` and `SecRateLimiter` in the same package.

## 6. Infrastructure Naming Rules (Mandatory)

1. Do not name concrete implementations as `*Port`.
2. Separate source adapter from aggregator:
   - single source: `*Provider`
   - multi-source fallback/cache orchestration: `*Service`
3. If both `Client` and `Provider` exist:
   - `Client` handles raw transport
   - `Provider` converts source payload to canonical model
4. Repository names must encode concrete storage intent.
5. Oversized "god" factories/services must be split by responsibility.

## 7. Placement Decision Checklist

Before adding a new class/function, answer:

1. Is this a business rule independent of I/O? -> `domain`.
2. Is this sequencing multiple steps/use-cases? -> `application`.
3. Is this reading/writing artifacts or external APIs? -> `infrastructure` (or legacy `data` during migration).
4. Is this shape validation/serialization/mapping for boundaries? -> `interface`.
5. Is this LangGraph node wiring only? -> `workflow`.

Boundary payload rule:

1. Workflow state updates and interrupt payloads are boundary payloads.
2. Domain VO/entity -> JSON mapping belongs to `interface/serializers.py` (or `interface/mappers.py` for lightweight cases), not in workflow nodes.

## 8. Review Checklist for PRs

1. Is class suffix aligned with actual responsibility?
2. Is file name aligned with main class?
3. Is any concrete class still named `*Port`?
4. Is infrastructure class leaking domain decisions?
5. Any import-time side effects introduced?
6. Any mixed acronym style in one package?
7. Any oversized service/factory that should be decomposed?

## 9. Definition of Done for Agent Refactor

1. Workflow nodes are thin and orchestration-only.
2. Domain owns core business rules and deterministic logic.
3. External integrations are in infrastructure (or explicit legacy `data` shim during transition).
4. Public artifact contracts live in `interface/contracts.py`.
5. Tests cover:
   - domain services/policies
   - application orchestration/use-cases
   - interface parser/mapper/serializer
   - infrastructure adapter behavior
