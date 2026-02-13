# Deep Refactor Master Plan (Big-Bang, Zero Leftover)
Date: 2026-02-13
Status: Approved for execution
Scope: `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core`
Policy: Zero compatibility, fail-fast, contract-first, no leftover transitional architecture.

## 1. Objective

Perform a one-shot structural refactor to achieve clear package ownership and strict clean architecture boundaries for all sub-agents.

Success means:
1. No global mixed ownership contract file for all agents.
2. No global mixed ownership per-agent port implementation file.
3. Workflow nodes are orchestration-only (no parsing/mapping/storage mechanics).
4. Cross-agent data exchange is only via public artifact contracts (kind/version envelope).
5. Dependency direction is mechanically enforced by CI.

## 2. Non-Negotiable Constraints

1. No compatibility fallbacks.
2. No dual architecture kept in parallel after cutover.
3. Producer and consumer are changed atomically in same PR set.
4. Any file violating target layer boundaries must be moved or rewritten in this project.

## 3. Target Architecture (Final)

```text
finance-agent-core/src/
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

  orchestration/
  api/
```

## 4. Current Main Problems to Remove

1. Contract ownership centralized in `src/interface/artifact_domain_models.py`.
2. Port ownership centralized in `src/services/domain_artifact_ports.py`.
3. Node files mixing orchestration + parser + persistence + formatting.
4. Agent policy files importing data-layer implementations (layer direction leak).

## 5. Execution Strategy

We will execute a strict 7-wave big-bang sequence and cut over permanently at Wave 6.

## Wave 0: Guardrails First (Mandatory)

Goal:
1. Prevent new boundary violations during migration.

Tasks:
1. Add import boundary rules (import-linter or equivalent checks in CI).
2. Add fail-fast policy checks for forbidden imports per layer.
3. Freeze new feature work in touched modules until cutover completed.

Exit criteria:
1. CI fails on prohibited dependency edges.
2. Team agrees freeze scope list.

## Wave 1: Package Skeleton + Shared Base

Goal:
1. Create final directory skeleton without moving behavior yet.

Tasks:
1. Create `src/agents/{fundamental,news,technical,debate}/{domain,application,data,interface}`.
2. Create `src/shared/{domain,application,data,interface}`.
3. Move only neutral envelope/base primitives into `shared/interface`.

Exit criteria:
1. New package skeleton exists.
2. No business semantics moved into shared accidentally.

## Wave 2: Contract Ownership Split (Per Agent)

Goal:
1. Remove global contract ownership.

Tasks:
1. Split contracts from `src/interface/artifact_domain_models.py` into:
   - `agents/fundamental/interface/contracts.py`
   - `agents/news/interface/contracts.py`
   - `agents/technical/interface/contracts.py`
   - `agents/debate/interface/contracts.py`
2. Keep only envelope/base contract in `shared/interface`.
3. Update registry to import per-agent public contracts only.

Exit criteria:
1. `artifact_domain_models.py` removed.
2. All contract tests pass.

## Wave 3: Port Ownership Split (Per Agent)

Goal:
1. Remove global mixed port ownership.

Tasks:
1. Keep generic typed port in `shared/data/typed_artifact_port.py`.
2. Split concrete ports from `src/services/domain_artifact_ports.py` into:
   - `agents/fundamental/data/ports.py`
   - `agents/news/data/ports.py`
   - `agents/technical/data/ports.py`
   - `agents/debate/data/ports.py`
3. Rebind runtime wiring to new per-agent ports.

Exit criteria:
1. `domain_artifact_ports.py` removed.
2. All artifact API and error-handling tests pass.

## Wave 4: Application Extraction from Nodes

Goal:
1. Make nodes orchestration-only.

Tasks:
1. For each agent, extract from `nodes.py`:
   - parsing/normalization helpers -> interface
   - report/data extraction helpers -> application services
   - persistence calls -> data ports
2. Node functions keep only:
   - state read/write
   - step transitions
   - use-case invocation

Exit criteria:
1. Nodes contain no direct contract parsing or serialization logic.
2. Line count of each `nodes.py` reduced by >=35% from baseline.

## Wave 5: Mapper Split (Derive vs Format)

Goal:
1. Remove mixed responsibility in preview mappers.

Tasks:
1. Split each mapper into:
   - application view-model derivation
   - interface display formatting (emoji/string/localization)
2. Keep business-derived metrics (ROE etc.) out of display formatter.

Exit criteria:
1. Derivation and formatting have separate tests and modules.

## Wave 6: Cutover + Removal

Goal:
1. Remove all transitional leftovers.

Tasks:
1. Delete old modules:
   - old global contracts
   - old global ports
   - obsolete intermediate adapters
2. Update docs to new authoritative architecture only.
3. Run full contract generation and fixture validation.

Exit criteria:
1. No code references to removed modules.
2. No TODO/compat markers in runtime path.

## Wave 7: Hardening and Audit Pack

Goal:
1. Ensure long-term maintainability and audit readiness.

Tasks:
1. Add architecture decision records (ADR) for package boundaries.
2. Add CI job that prints dependency graph and validates layer rules.
3. Produce final audit summary of before/after module map.

Exit criteria:
1. CI guards active.
2. Audit artifacts complete.

## 6. Definition of Done (Global, Zero Leftover)

All must be true:
1. No file `src/interface/artifact_domain_models.py`.
2. No file `src/services/domain_artifact_ports.py`.
3. No sub-agent imports another sub-agent internal layer (except interface public contracts).
4. Nodes do not import persistence implementations directly.
5. Contract parsing exists only in interface boundary modules.
6. CI boundary checks green.
7. Core backend test matrix green.

## 7. Test Matrix (Mandatory)

1. `finance-agent-core/tests/test_protocol.py`
2. `finance-agent-core/tests/test_mappers.py`
3. `finance-agent-core/tests/test_news_mapper.py`
4. `finance-agent-core/tests/test_debate_mapper.py`
5. `finance-agent-core/tests/test_artifact_api_contract.py`
6. `finance-agent-core/tests/test_output_contract_serializers.py`
7. `finance-agent-core/tests/test_error_handling_fundamental.py`
8. `finance-agent-core/tests/test_error_handling_news.py`
9. `finance-agent-core/tests/test_error_handling_technical.py`
10. `finance-agent-core/tests/test_param_builder_canonical_reports.py`

## 8. Risk Register and Mitigation

1. Risk: High merge conflict due to large moves.
   - Mitigation: Wave-by-wave PRs but no compatibility code, only atomic cutover per wave.
2. Risk: Hidden circular imports after split.
   - Mitigation: boundary lint check before each wave merge.
3. Risk: Runtime drift in artifact contracts.
   - Mitigation: artifact contract tests + fixture tests required per wave.

## 9. Delivery Format

Execution will be delivered in sequential PR-sized waves with strict closure per wave.
No wave can leave temporary runtime compatibility code behind.
