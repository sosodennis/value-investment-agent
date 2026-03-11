# Fundamental Cohesion/Fragmentation Scan + Facade Export Plan

## Requirement Breakdown
- Scan `src/agents/fundamental` for over-fragmented clusters and deep import paths.
- Propose consolidation targets that increase cohesion without breaking subdomain boundaries.
- Define facade export plan to hide deep internals and stabilize external imports.
- Keep refactor phases small/medium and compatible with clean-cut subdomain boundaries.
- No compatibility shims unless explicitly approved.

## Technical Objectives and Strategy
- Reduce over-fragmentation (multiple single-purpose modules used together in one path).
- Reduce deep import exposure (imports should go through subdomain or explicit entrypoints).
- Keep pipeline stage grouping where it provides real boundary value.
- Preserve functional behavior and workflow contracts.
- Maintain unidirectional dependency flow between subdomains.

## Involved Files
- `finance-agent-core/src/agents/fundamental/wiring.py`
- `finance-agent-core/src/agents/fundamental/workflow_orchestrator/application/*`
- `finance-agent-core/src/agents/fundamental/core_valuation/domain/parameterization/**`
- `finance-agent-core/src/agents/fundamental/financial_statements/infrastructure/sec_xbrl/**`
- `finance-agent-core/src/agents/fundamental/forward_signals/infrastructure/sec_xbrl/**`
- `finance-agent-core/src/agents/fundamental/financial_statements/interface/*`
- `finance-agent-core/src/agents/fundamental/forward_signals/interface/*`

## Detailed Per-File Plan

### Phase 1 (small): Facade export definition
Objective:
- Establish stable entrypoints and stop deep external imports.

Changes (plan only):
- Create/expand `financial_statements/infrastructure/sec_xbrl/__init__.py` to export:
  - `fetch_financial_payload` (currently in `fetch/provider.py`).
- Create/expand `forward_signals/infrastructure/sec_xbrl/__init__.py` to export:
  - `extract_forward_signals_from_xbrl_reports` (currently in `forward_signals.py`).
- Create/expand `core_valuation/domain/parameterization/__init__.py` to export:
  - `ParamBuildResult`, `build_params`, and `apply_missing_metric_policy` (currently deep in `model_builders/shared/missing_metrics_service.py`).

Entry/Exit:
- Entry: no runtime behavior changes.
- Exit: external imports can be switched to subdomain entrypoints.

Validation:
- `ruff check finance-agent-core/src/agents/fundamental`
- Targeted tests for valuation and workflow orchestration (see Validation section).

### Phase 2 (medium): Contract surface cleanup to break deep cross-subdomain imports
Objective:
- Remove deep cross-subdomain import dependencies.

Changes (plan only):
- Promote `financial_statements.infrastructure.sec_xbrl.extract.report_contracts.FinancialReport`
  to `financial_statements/interface/contracts.py` or `shared/contracts` (single canonical type).
- Update `forward_signals.infrastructure.sec_xbrl.forward_signals` to depend on the interface contract
  instead of infrastructure internals.
- Update any other consumers to use the new interface contract location.

Entry/Exit:
- Entry: Phase 1 complete.
- Exit: no imports from `financial_statements.infrastructure.sec_xbrl.extract` outside that subdomain.

Validation:
- `rg "financial_statements\\.infrastructure\\.sec_xbrl\\.extract" finance-agent-core/src -g"*.py"` (should be internal-only)
- Targeted tests for forward_signals + financial_statements.

### Phase 3 (medium): Cohesion consolidation in high-fragmentation clusters
Objective:
- Reduce file-count and cross-file hopping in tightly coupled pipelines.

Changes (plan only):
- **Forward signals retrieval**:
  - Consolidate `hybrid_retriever_*_service.py` and `text_record.py` into a single
    `hybrid_retriever.py` or `retrieval_pipeline.py` module.
  - Keep `sentence_pipeline.py`, `filing_text_loader.py`, `focus_text_extractor.py` as
    coarse-grained stages if used independently.
- **Forward signals matching**:
  - Fold `pipeline_scalar_service.py` into `record_processor_metric_service.py`
    if it is only used there.
- **Financial statements extract**:
  - Group `base_model_income_cashflow_*` into a single `income_cashflow_pipeline.py`
    and `base_model_debt_*` into `debt_pipeline.py`, if they are always used together.
- **Core valuation parameterization/shared**:
  - Consider merging `capital_structure_value_extraction_service.py`,
    `equity_market_value_extraction_service.py`, and `market_value_extraction_service.py`
    into one `market_value_extraction.py` module if they are always co-invoked.

Entry/Exit:
- Entry: Phase 2 complete.
- Exit: reduced module count, fewer deep paths, no behavior change.

Validation:
- `ruff check finance-agent-core/src/agents/fundamental`
- Targeted tests for valuation + forward_signals + financial_statements.

### Phase 4 (small): Facade migration sweep
Objective:
- Migrate call sites to facades and remove deep external imports.

Changes (plan only):
- Update imports in:
  - `fundamental/wiring.py`
  - `workflow_orchestrator/application/*`
  - any other external references to deep `sec_xbrl` or `model_builders/shared` modules.
- Run legacy import sweep.

Validation:
- `rg "financial_statements\\.infrastructure\\.sec_xbrl\\.(extract|fetch|map)" finance-agent-core/src -g"*.py"`
- `rg "core_valuation\\.domain\\.parameterization\\.model_builders\\.shared" finance-agent-core/src -g"*.py"`

## Old → New Mapping
(Tentative, to be finalized after confirmation)
- `financial_statements.infrastructure.sec_xbrl.fetch.provider.fetch_financial_payload`
  → `financial_statements.infrastructure.sec_xbrl.fetch_financial_payload`
- `core_valuation.domain.parameterization.model_builders.shared.missing_metrics_service.apply_missing_metric_policy`
  → `core_valuation.domain.parameterization.apply_missing_metric_policy`
- `financial_statements.infrastructure.sec_xbrl.extract.report_contracts.FinancialReport`
  → `financial_statements.interface.contracts.FinancialReport` (or `shared/contracts`)
- Forward signals retrieval small modules → consolidated `retrieval/hybrid_retriever.py`
- Base-model extraction clusters → consolidated `extract/income_cashflow_pipeline.py`,
  `extract/debt_pipeline.py` (if cohesion check confirms)

## Cohesion/Facade Plan

### Fragmentation Hotspots
- `financial_statements/infrastructure/sec_xbrl/extract/*`:
  - Many tightly-coupled base_model modules (income_cashflow + debt) that likely operate as a unit.
- `forward_signals/infrastructure/sec_xbrl/retrieval/*`:
  - Very small helper modules (`hybrid_retriever_*`, `text_record.py`) that likely belong together.
- `core_valuation/domain/parameterization/model_builders/shared/*`:
  - Multiple value extraction services that tend to be invoked together.

### Facade Targets (Public API Surface)
- `financial_statements.infrastructure.sec_xbrl`:
  - `fetch_financial_payload`, plus any public types needed by other subdomains.
- `forward_signals.infrastructure.sec_xbrl`:
  - `extract_forward_signals_from_xbrl_reports` only.
- `core_valuation.domain.parameterization`:
  - `build_params`, `ParamBuildResult`, `apply_missing_metric_policy`.

### Deep Import Elimination Targets
- `fundamental/wiring.py` (currently imports deep `sec_xbrl.fetch.provider`).
- `workflow_orchestrator/application/valuation_flow.py`
  (imports `core_valuation.domain.parameterization.model_builders.shared.missing_metrics_service`).
- `forward_signals/infrastructure/sec_xbrl/forward_signals.py`
  (imports `financial_statements.infrastructure.sec_xbrl.extract.report_contracts`).

## Risk/Dependency Assessment
- Moderate risk: moving contracts may ripple across multiple subdomains.
- Moderate risk: consolidating pipeline modules could inadvertently change init order or defaults.
- Low risk: facade export additions and import rewrites.

## Validation and Rollout Gates
- Lint: `ruff check finance-agent-core/src/agents/fundamental`
- Targeted tests (minimum):
  - `finance-agent-core/tests/test_fundamental_mapper.py`
  - Any tests covering forward signals extraction and financial payload fetch.
- Migration hygiene:
  - `rg` sweep for deep import paths after facade migration.
  - Ensure no external imports into `sec_xbrl/extract/*` or `model_builders/shared/*`.

## Assumptions/Open Questions
- No external (non-repo) consumers import deep fundamental paths.
- Confirm whether `FinancialReport` should live in `financial_statements/interface` vs `shared/contracts`.
- Validate whether base-model extraction modules are always co-invoked; if not, skip consolidation.
