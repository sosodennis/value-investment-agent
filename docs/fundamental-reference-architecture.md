# Fundamental Reference Architecture (After Deep Refactor)
Date: 2026-02-13
Status: Active reference implementation for remaining sub-agent migrations.

## 1. Purpose

This document is the concrete boundary playbook extracted from the `fundamental_analysis` deep refactor.
Use it as the template for `news`, `technical`, and `debate`.

## 2. Final Runtime Shape (Fundamental)

1. Workflow orchestration only:
   - `src/workflow/nodes/fundamental_analysis/nodes.py`
2. Agent package owns business/runtime logic:
   - `src/agents/fundamental/domain/**`
   - `src/agents/fundamental/application/**`
   - `src/agents/fundamental/data/**`
   - `src/agents/fundamental/interface/**`

## 3. Placement Rules (What goes where)

### 3.1 Domain
Put code here if changing it changes valuation outcome.

Moved examples:
1. `tools/model_selection.py` -> `agents/fundamental/domain/model_selection.py`
2. `tools/valuation/**` -> `agents/fundamental/domain/valuation/**`
3. Financial semantics primitives:
   - `agents/fundamental/domain/models.py`
   - `agents/fundamental/domain/entities.py`
   - `agents/fundamental/domain/rules.py`
   - `agents/fundamental/domain/value_objects.py`

### 3.2 Application
Put code here if it coordinates use-cases and state transitions, but does not own framework graph wiring.

Implemented:
1. `agents/fundamental/application/use_cases.py`
2. `agents/fundamental/application/orchestrator.py`
3. `agents/fundamental/application/ports.py`
4. `agents/fundamental/application/dto.py`

### 3.3 Data
Put code here if it talks to external providers/persistence.

Moved examples:
1. `tools/sec_xbrl/**` -> `agents/fundamental/data/clients/sec_xbrl/**`
2. `tools/profiles.py` -> `agents/fundamental/data/clients/profiles.py`
3. `tools/tickers.py` -> `agents/fundamental/data/clients/tickers.py`
4. `tools/web_search.py` -> `agents/fundamental/data/clients/web_search.py`
5. Artifact persistence port remains in:
   - `agents/fundamental/data/ports.py`

### 3.4 Interface
Put code here if it is contract/parser/serializer/formatting.

Examples:
1. `agents/fundamental/interface/contracts.py`
2. `agents/fundamental/interface/mappers.py`
3. `agents/fundamental/interface/formatters.py`
4. `tools/report_helpers.py` -> `agents/fundamental/interface/report_helpers.py`

## 4. What was removed from workflow package

1. Deleted local tools package:
   - `src/workflow/nodes/fundamental_analysis/tools/`
2. Deleted local structures file (moved semantics into domain models):
   - `src/workflow/nodes/fundamental_analysis/structures.py`
3. Intent extraction no longer imports fundamental internals through workflow paths.

## 5. Dependency Rules proven in this refactor

1. `workflow` imports `agents/*/application` (and selected domain model types if needed) instead of local `tools`.
2. `intent_extraction` no longer imports `fundamental_analysis.tools.*`.
3. Cross-agent model coupling reduced to shared/domain contracts.
4. Architecture boundary checker runs with zero baseline violations.

## 6. Verification commands used

1. Ruff:
   - `uv run --project finance-agent-core python -m ruff check <touched-files>`
2. Test matrix:
   - `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_protocol.py finance-agent-core/tests/test_mappers.py finance-agent-core/tests/test_news_mapper.py finance-agent-core/tests/test_debate_mapper.py finance-agent-core/tests/test_artifact_api_contract.py finance-agent-core/tests/test_output_contract_serializers.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_error_handling_news.py finance-agent-core/tests/test_error_handling_technical.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_domain_artifact_ports_fundamental.py finance-agent-core/tests/test_fundamental_application_services.py finance-agent-core/tests/test_interrupts.py finance-agent-core/tests/test_intent_application_use_cases.py -q`
3. Boundary gate:
   - `python3 scripts/check_architecture_boundaries.py`

## 7. Migration Template for next sub-agent

For `news` / `technical` / `debate`:
1. Move workflow-local `tools/*` into `agents/<agent>/{domain|data|interface}`.
2. Add `application/orchestrator.py` as single workflow entrypoint.
3. Remove workflow-local `tools/` package.
4. Rewire imports in workflow nodes and tests.
5. Update progress docs in same PR.
6. Run matrix + boundary checks.
