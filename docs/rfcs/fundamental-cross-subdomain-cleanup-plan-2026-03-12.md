# Fundamental Cross-Subdomain Cleanup Plan (2026-03-12)

## Requirement Breakdown
- Remove cross-subdomain infrastructure dependencies between `financial_statements` and `forward_signals`.
- Move forward-signal extraction out of `financial_statements` infrastructure into application-level orchestration.
- Keep enterprise topology (`application/`, `domain/`, `interface/`, `subdomains/`) and subdomain layering intact.
- No compatibility shims or dual-path imports.
- Preserve existing artifact payload shape (`financial_reports`, `forward_signals`, `diagnostics`, `quality_gates`) in the fundamental workflow output.

## Technical Objectives and Strategy
- **Objective 1**: `financial_statements` infra returns only financial reports + diagnostics/quality gates.
- **Objective 2**: `forward_signals` extraction is owned by `forward_signals` application service and invoked from root `fundamental/application` orchestration.
- **Objective 3**: Eliminate infra-to-infra cross-subdomain imports by duplicating minimal SEC retry helper inside `forward_signals` infra (or later promote to `src/shared/edgar/*` if reused across agents).
- **Objective 4**: Update contracts/parsers and orchestration signatures to reflect the split.

## Involved Files
- `finance-agent-core/src/agents/fundamental/subdomains/financial_statements/infrastructure/sec_xbrl/extract/financial_payload_service.py`
- `finance-agent-core/src/agents/fundamental/subdomains/financial_statements/infrastructure/sec_xbrl/__init__.py`
- `finance-agent-core/src/agents/fundamental/subdomains/financial_statements/interface/parsers.py`
- `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/financial_health_flow.py`
- `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/orchestrator.py`
- `finance-agent-core/src/agents/fundamental/application/wiring.py`
- `finance-agent-core/src/agents/fundamental/subdomains/forward_signals/infrastructure/sec_xbrl/retrieval/text_signal_record_loader_service.py`
- New: `finance-agent-core/src/agents/fundamental/subdomains/forward_signals/application/`
- Tests: `finance-agent-core/tests/test_sec_xbrl_financial_payload_service.py`, `finance-agent-core/tests/test_sec_xbrl_forward_signals.py`, `finance-agent-core/tests/test_fundamental_orchestrator_logging.py`, `finance-agent-core/tests/test_error_handling_fundamental.py`

## Layer Topology and Shared Kernel Placement
- Root remains: `application/`, `domain/`, `interface/`, `subdomains/`.
- Shared kernel remains only at `fundamental/domain/shared/`.
- Cross-subdomain orchestration remains in root `fundamental/application`.
- `forward_signals` gains an `application/` package for extraction orchestration.

## Detailed Per-File Plan
1. **Financial Statements payload split**
   - Update `financial_payload_service.py` to stop importing forward-signals infra.
   - Rename `fetch_financial_payload` → `fetch_financial_reports_payload` (or equivalent) and return only:
     - `financial_reports`
     - `diagnostics`
     - `quality_gates`
   - Update `sec_xbrl/__init__.py` export to the new function name.

2. **Financial statements interface contract**
   - Replace `FinancialHealthPayload` with `FinancialStatementsPayload` in `interface/parsers.py`.
   - Remove `forward_signals` from required keys and parser output.

3. **Forward signals application service**
   - Add `subdomains/forward_signals/application/` package.
   - Add `ports.py` (protocols for XBRL + text extraction) and `extraction_service.py` (or `forward_signal_extraction_service.py`).
   - Service signature: accepts `ticker`, `financial_reports` and optional `diagnostics`/`quality_gates` if required, plus extractor ports.

4. **Remove infra-to-infra retry import**
   - Add minimal SEC retry helper in `forward_signals/infrastructure/sec_xbrl/sec_retry.py` (duplicate logic, no cross-subdomain import).
   - Update `text_signal_record_loader_service.py` to use local retry helper.

5. **Root application orchestration**
   - Update `financial_health_flow.py` to:
     - Call `fetch_financial_reports_payload` (financial statements)
     - Call new forward-signals application service
     - Build artifact payload with reports + forward_signals + diagnostics + quality_gates
   - Update `orchestrator.py` and `wiring.py` to pass separate callables/ports for reports + forward signals.

6. **Tests and import hygiene**
   - Update tests expecting `FinancialHealthPayload` and `fetch_financial_payload` to the new names/shape.
   - Add/adjust tests to assert forward signals still appear in artifact payload, but are now produced by the new service.

## Old → New Mapping
- `financial_statements.infrastructure.sec_xbrl.fetch_financial_payload`
  → `financial_statements.infrastructure.sec_xbrl.fetch_financial_reports_payload`
- `FinancialHealthPayload`
  → `FinancialStatementsPayload`
- `financial_payload_service` (forward-signals extraction responsibility)
  → `forward_signals/application/extraction_service` + root `financial_health_flow` orchestration
- `forward_signals` infra SEC retry import from `financial_statements`
  → `forward_signals.infrastructure.sec_xbrl.sec_retry.call_with_sec_retry`

## Cohesion/Facade Plan
- `financial_statements/infrastructure/sec_xbrl/__init__.py` exports only the top-level fetch function.
- `forward_signals/application/__init__.py` exports `extract_forward_signals` (or equivalent).
- External callers import only subdomain entrypoints, not deep infra paths.

## Risk/Dependency Assessment
- **Behavioral risk**: forward signals may be missing if orchestration order changes.
- **Contract risk**: downstream code expects `FinancialHealthPayload` shape.
- **Runtime risk**: additional `asyncio.to_thread` calls for forward signals extraction.
- **Rollback**: changes are isolated to application orchestration and contracts; revert by restoring old function names and payload shape.

## Validation and Rollout Gates
- Lint: `uv run --project finance-agent-core python -m ruff check`.
- Tests:
  - `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_sec_xbrl_financial_payload_service.py -q`
  - `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_sec_xbrl_forward_signals.py -q`
  - `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q`
  - `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_error_handling_fundamental.py -q`
- Import hygiene:
  - `rg "subdomains\\.financial_statements\\.infrastructure" finance-agent-core/src/agents/fundamental/subdomains/forward_signals`
  - `rg "subdomains\\.forward_signals\\.infrastructure" finance-agent-core/src/agents/fundamental/subdomains/financial_statements`

## Assumptions/Open Questions
- The forward-signals extraction can operate with `financial_reports` only. If it requires additional inputs (e.g., normalized SEC text), define explicit optional inputs in the application service signature.
- The SEC retry helper is duplicated for now. If reuse expands across agents, promote to a shared cross-agent module later (`src/shared/edgar/*`).
