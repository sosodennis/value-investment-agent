# Sub-Agent Package Architecture Guideline
Date: 2026-02-13
Status: Active (normative)
Scope: `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src`

## 1. Goal

This guideline defines where code should live in a multi-agent backend so engineers do not spend time debating placement for every feature.

Primary goals:
1. Keep agent boundaries explicit.
2. Keep cross-agent dependencies contract-first.
3. Keep business rules framework/storage independent.
4. Keep ownership clear by package.

## 2. Package Strategy

Each sub-agent owns its package. Shared code is allowed but strictly limited.

Target shape:

```text
src/
  shared/
    domain/
    application/
    data/
    interface/
  agents/
    fundamental/
      domain/
      application/
      data/
      interface/
    news/
      domain/
      application/
      data/
      interface/
    technical/
      domain/
      application/
      data/
      interface/
    debate/
      domain/
      application/
      data/
      interface/
```

## 3. Layer Responsibilities

### 3.1 `domain/`

Contains business semantics and invariants.

Examples:
1. Model selection scoring policies.
2. Financial metric rules (ROE, growth logic).
3. Debate decision scoring logic.

Forbidden:
1. ORM/DB code.
2. HTTP/LLM client calls.
3. API DTO parsing.

### 3.2 `application/`

Contains use-case orchestration for one agent.

Examples:
1. Node-level workflow steps.
2. Use-case services combining domain + ports.
3. Coordination logic and progress transitions.
4. Agent-facing orchestrator entrypoint consumed by `src/workflow/**`.

Forbidden:
1. Low-level persistence format handling.
2. External provider client details.

### 3.3 `data/`

Contains persistence and external provider adapters.

Examples:
1. Artifact repository implementations.
2. SEC/news/market client adapters.
3. Data-source specific mapping to app/domain inputs.

Forbidden:
1. Business decisions and scoring.

### 3.4 `interface/`

Contains transport contracts and boundary adapters.

Examples:
1. Public artifact contract models.
2. Parser/serializer for API/SSE/artifact payloads.
3. Preview/output DTO mappers.

Forbidden:
1. Business policy decisions.

## 4. Shared Package Rules

`shared` is not a dumping ground.

Promote to `shared` only when all are true:
1. Used by at least 3 locations.
2. Stable (not changing every sprint).
3. Semantically neutral (not tied to one agent's business meaning).

If uncertain, keep it in the owning agent package first.

## 5. Dependency Rules (Strict)

1. `shared` must not import from `agents/*`.
2. `agents/*/domain` must not import from `data` or framework-specific modules.
3. Cross-agent access is allowed only via public contracts.
4. Debate cannot import another agent's internal domain/application/data modules.
5. Cross-agent reads must use envelope + expected kind/version validation.

## 6. Public Artifact Contracts (Per Agent)

Each producer agent publishes its own public artifact contract under its `interface` package.

Recommended files:
1. `agents/<agent>/interface/contracts.py` (kind/version + DTO)
2. `agents/<agent>/interface/parsers.py` (fail-fast parser)
3. `agents/<agent>/interface/serializers.py` (domain/app to contract)

`shared/interface` only defines exchange framework:
1. Envelope schema.
2. Shared base types.
3. Common serialization primitives.

## 7. What Is a Business Rule

A rule is business rule if changing it changes business outcome.

Quick test:
1. If changed, will valuation/risk/verdict change?
2. Is it driven by financial semantics rather than framework/storage?
3. Can it run without HTTP/DB/ORM context?

If yes, place in `domain` (or `application` policy layer if orchestration-bound).

## 8. Tools Placement Rule

Do not use `tools` as a mixed bucket.

1. External I/O adapters -> `data/`.
2. Pure deterministic logic -> `domain/`.
3. Use-case glue helpers -> `application/`.
4. Contract parsing/serialization helpers -> `interface/`.

## 9. Placement Decision Checklist

For any new class/function:
1. Is it business semantics? -> `domain`.
2. Is it workflow/use-case coordination? -> `application`.
3. Is it external storage/provider integration? -> `data`.
4. Is it request/response/artifact DTO parse/map? -> `interface`.

If still unclear, choose owner-agent local placement first, not `shared`.

## 10. Required CI Guardrails

1. Import boundary checks (e.g. import-linter style rules).
2. Contract tests for artifact/API boundaries.
3. Parser fail-fast tests for invalid payloads.
4. Zero compatibility fallback in runtime contract path.

## 11. Workflow Boundary Rule (Target End-State)

1. `src/workflow/**` should import `src/agents/*/application/**` only.
2. `src/workflow/**` should not import `src/agents/*/data/**` or `src/agents/*/interface/**` directly.
3. During migration, any exception must be documented in progress tracker with removal plan.
