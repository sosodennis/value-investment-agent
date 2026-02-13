# Agent Cross-Review (Intent / Fundamental / News / Technical)
Date: 2026-02-13
Scope: `finance-agent-core/src/agents/{intent,fundamental,news,technical}`
Reference: `docs/agent-layer-responsibility-and-naming-guideline.md`

## Executive Summary

1. `intent`: boundary ownership improved (`contracts` and `policies` moved to correct layers).
2. `fundamental`: workflow nodes are thin orchestration adapters; report semantics are now centralized in one source.
3. `news`: boundary convergence completed (policy in domain, payload assembly in interface).
4. `technical`: boundary convergence completed (semantic rules in domain, payload assembly in interface).

## Findings by Agent

## Intent

Status: GOOD

Evidence:
1. Application orchestrator centralizes flow:
   - `finance-agent-core/src/agents/intent/application/orchestrator.py`
2. Data clients are in agent data layer:
   - `finance-agent-core/src/agents/intent/data/market_clients.py`
3. Domain model is isolated:
   - `finance-agent-core/src/agents/intent/domain/models.py`
4. Boundary models moved to interface contracts:
   - `finance-agent-core/src/agents/intent/interface/contracts.py`
5. Clarification rule moved to domain policy:
   - `finance-agent-core/src/agents/intent/domain/policies.py`

Notes:
1. Intent application helper naming is now converged to `application/use_cases.py`.

## Fundamental

Status: GOOD

Evidence:
1. Layering exists across domain/application/data/interface.
2. Workflow nodes now delegate main behavior to application orchestrator methods:
   - `finance-agent-core/src/workflow/nodes/fundamental_analysis/nodes.py`
   - `finance-agent-core/src/agents/fundamental/application/orchestrator.py`
3. Domain valuation package is substantial and separated.
4. Financial report semantic rules are now centralized:
   - `finance-agent-core/src/agents/fundamental/domain/report_semantics.py`
5. Interface/domain adapters use shared semantic helpers instead of local duplicates:
   - `finance-agent-core/src/agents/fundamental/interface/contracts.py`
   - `finance-agent-core/src/agents/fundamental/domain/valuation/report_contract.py`
6. Preview metric extraction (including ROE inputs) is centralized in domain services:
   - `finance-agent-core/src/agents/fundamental/domain/services.py`
   - `finance-agent-core/src/agents/fundamental/application/view_models.py`
7. Valuation success `equity_value` selection rule is centralized in domain services:
   - `finance-agent-core/src/agents/fundamental/domain/services.py`
   - `finance-agent-core/src/agents/fundamental/application/use_cases.py`

Residual note:
1. `data/clients/sec_xbrl/models.py` remains ingestion-focused and should not become a second semantic-rule owner.

## News

Status: GOOD

Evidence:
1. Domain layer now exists:
   - `finance-agent-core/src/agents/news/domain/services.py`
2. Orchestrator exists:
   - `finance-agent-core/src/agents/news/application/orchestrator.py`
3. Data clients moved under agent:
   - `finance-agent-core/src/agents/news/data/clients/*`

Resolved boundary changes:
1. Search strategy policy moved to domain:
   - `finance-agent-core/src/agents/news/domain/policies.py`
2. Domain result is semantic-only:
   - `finance-agent-core/src/agents/news/domain/models.py`
   - `finance-agent-core/src/agents/news/domain/services.py`
3. Contract payload assembly moved to interface:
   - `finance-agent-core/src/agents/news/interface/serializers.py`

## Technical

Status: GOOD

Evidence:
1. Orchestrator exists:
   - `finance-agent-core/src/agents/technical/application/orchestrator.py`
2. Domain layer now exists:
   - `finance-agent-core/src/agents/technical/domain/services.py`
3. Tools moved under agent data layer:
   - `finance-agent-core/src/agents/technical/data/tools/*`

Resolved boundary changes:
1. Semantic decision rules moved to domain policy:
   - `finance-agent-core/src/agents/technical/domain/policies.py`
2. Data semantic layer now only handles LLM interpretation adapter:
   - `finance-agent-core/src/agents/technical/data/tools/semantic_layer.py`
3. Report payload assembly moved to interface serializer:
   - `finance-agent-core/src/agents/technical/interface/serializers.py`

## Cross-Agent Naming Consistency Check

Current status:
1. Legacy `structures.py` in `news/technical` has been removed.
2. Boundary models now use explicit `interface/contracts.py` naming.
3. `news/technical` application flow helpers are now standardized as `application/use_cases.py`.
4. `intent` application flow helpers are now standardized as `application/use_cases.py`.

Required target:
1. Domain semantic types: `domain/models.py`
2. Interface contracts: `interface/contracts.py`
3. Do not introduce new `structures.py` in agent packages.

## Priority Actions Before Debate Refactor

1. News boundary cleanup completed.
2. Technical boundary cleanup completed.
3. Keep `debate` unchanged until a dedicated wave starts with the same package pattern.
