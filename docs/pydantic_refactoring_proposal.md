# Pydantic Refactoring Proposal (Aligned with Current Architecture)

**Date:** 2026-02-13
**Status:** Proposed (Aligned)
**Scope:** `finance-agent-core` backend contract models (`src/agents/*/interface/contracts.py`, `src/interface/*`)

## 1. Purpose

This proposal refines how we reduce Pydantic validator boilerplate **without violating** current project architecture:

1. `Zero compatibility`
2. `Fail-fast parsing`
3. `Contract-first`
4. Clean architecture boundaries (`domain/application/data/interface`)

This document replaces earlier assumptions based on "dirty coercion" workflows.

## 2. Current Baseline (Authoritative)

The current system already enforces:

1. Boundary validation through interface contracts and artifact registry:
   - `src/interface/artifacts/artifact_contract_registry.py`
   - `src/agents/*/interface/contracts.py` (agent-local canonicalization entrypoints)
   - `src/shared/cross_agent/data/typed_artifact_port.py`
2. Strict no-compat policy:
   - `docs/clean-architecture-engineering-guideline.md`
   - `docs/backend-guideline.md`
3. Shared low-level parsing helpers:
   - `src/interface/artifacts/artifact_model_shared.py`

Therefore, any Pydantic refactor must preserve strict behavior and existing contract semantics.

## 3. What We Keep / What We Change

## 3.1 Keep (Must Not Regress)

1. `model_validator` logic that performs **business semantics**:
   - e.g. fundamental extension type inference, industry normalization, traceable shape rules.
2. Fail-fast behavior for unsupported values/types.
3. Agent-specific semantic contracts under `src/agents/<agent>/interface/contracts.py`.

## 3.2 Change (Boilerplate Reduction)

1. Replace repeated scalar/enum validators with reusable `Annotated[..., BeforeValidator(...)]` aliases.
2. Keep aliases local to each agent interface module (or agent-local `types.py`) unless truly shared.
3. Use `Annotated` for **format/primitive normalization only**, not cross-field domain decisions.

## 4. Architecture Rule for `Annotated`

`Annotated + BeforeValidator` is allowed only for:

1. Primitive string/number checks
2. enum token normalization
3. simple optional conversion rules

It is **not** used for:

1. cross-field invariants
2. extension type inference
3. domain-specific fallback/decision logic

Those remain explicit `model_validator` or domain service logic.

## 5. Recommended Pattern

## 5.1 Allowed Example (Interface primitive type)

```python
from typing import Annotated
from pydantic import BeforeValidator

StrictText = Annotated[str, BeforeValidator(lambda v: to_string(v, "field"))]
StrictNumber = Annotated[float, BeforeValidator(lambda v: to_number(v, "field"))]
```

Used in model fields where today we repeat identical `@field_validator` methods.

## 5.2 Not Allowed Example (Domain semantics hidden in type alias)

Do not hide logic like:

1. extension type inference from extension payload
2. defaulting `industry_type` from domain context
3. financial report semantic normalization

inside a generic alias. Keep explicit model/domain logic.

## 6. Migration Plan (Safe, Incremental)

## Phase 1: Technical Agent Interface (Low Risk)

1. Identify duplicated scalar validators in `technical/interface/contracts.py`.
2. Introduce local aliases (`StrictText`, `StrictFiniteNumber`, enum token alias).
3. Replace repetitive field validators where behavior is unchanged.
4. Keep cross-field logic untouched.

**Done criteria**
1. Same parsing behavior (tests pass unchanged)
2. Net validator boilerplate reduced
3. No compatibility fallback introduced

## Phase 2: News Agent Interface (Medium Risk)

1. Apply same pattern to repeated string/number/symbol validators.
2. Keep list/object structure checks explicit.
3. Do not collapse article/analysis semantics into generic aliases.

**Done criteria**
1. Contract tests unchanged
2. No behavior drift in sentiment/category normalization

## Phase 3: Debate Agent Interface (Medium Risk)

1. Extract repeated primitive validators.
2. Keep scenario/verdict/source semantics explicit.
3. Keep fact value type constraints explicit (string|number|null).

**Done criteria**
1. All debate contract tests unchanged
2. No hidden coercion added

## Phase 4: Fundamental Agent Interface (High Risk)

1. Only extract primitive repeated rules inside `TraceableFieldModel` usage.
2. Preserve all report semantic model validators.
3. Avoid flattening core report normalization into aliases.

**Done criteria**
1. Fundamental canonicalization behavior unchanged
2. Valuation pipeline remains stable
3. Existing regression suites pass

## 7. Non-Goals

1. No migration to `msgspec`.
2. No global "one file for all Robust types" that turns into shared bloat.
3. No rewrite of domain semantics into type aliases.
4. No compatibility mode for legacy payloads.

## 8. Tooling and Governance

For each migration slice:

1. Run `ruff` + targeted pytest + core regression suites.
2. Update only touched agent contract tests.
3. Keep changes atomic per agent.
4. If API schema changes, regenerate contracts in same PR.

## 9. Decision

We adopt **Pydantic `Annotated` selectively** as a boilerplate-reduction technique, under strict constraints:

1. Interface primitive normalization only
2. No change to business semantic validators
3. No compatibility paths
4. Preserve clean architecture boundaries

This provides maintainability gains while keeping current zero-compat contract architecture intact.
