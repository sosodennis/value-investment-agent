# Fundamental Subdomain Quality Audit and Refactor Plan (2026-03-11)

## Requirement Breakdown
- Analyze each fundamental subdomain for cohesion, fragmentation, and layer placement (domain/application/interface/infrastructure).
- Identify misplacements, generic catch-all modules, and empty/placeholder layers.
- Produce an implementation-ready plan (no code) to improve modular quality while keeping clean-cut boundaries.
- Output as a single RFC document under `docs/rfcs`.

## Technical Objectives and Strategy
- Enforce the cross-agent architecture standard: clean layer boundaries, no generic catch-all modules, typed boundaries, and no compatibility residue.
- Reduce structural noise by removing empty layers and consolidating overly-fragmented packages.
- Keep subdomains cohesive: a subdomain should own a bounded capability end-to-end; shared dependencies go only to `fundamental/shared/`.
- Ensure interface contracts are explicit for cross-subdomain data (avoid pervasive `dict[str, object]`).

### Structural Snapshot (non-__init__ Python files)
- `artifacts_provenance`: infrastructure 1, interface 1
- `core_valuation`: domain 93, interface 1
- `financial_statements`: domain 1, infrastructure 47, interface 3
- `forward_signals`: domain 9, infrastructure 36
- `market_data`: application 1, domain 3, infrastructure 7
- `model_selection`: domain 9, interface 1
- `shared`: contracts 1
- `workflow_orchestrator`: application 19, interface 5

Key signals:
- Multiple subdomains have empty application/domain/infrastructure layers (only `__init__.py`).
- Two infrastructures (`financial_statements/sec_xbrl`, `forward_signals/sec_xbrl`) are large and flat, with generic `*_utils` files.
- Interface-layer dependency on another subdomain’s domain service exists in `workflow_orchestrator/interface/preview_projection_service.py`.

## Involved Files
Scope: `finance-agent-core/src/agents/fundamental/*` and directly affected cross-agent boundaries.

Primary focus directories:
- `fundamental/artifacts_provenance/*`
- `fundamental/core_valuation/*`
- `fundamental/financial_statements/*`
- `fundamental/forward_signals/*`
- `fundamental/market_data/*`
- `fundamental/model_selection/*`
- `fundamental/shared/*`
- `fundamental/workflow_orchestrator/*`

Representative files (non-exhaustive):
- `fundamental/financial_statements/infrastructure/sec_xbrl/*.py`
- `fundamental/forward_signals/infrastructure/sec_xbrl/*.py`
- `fundamental/core_valuation/domain/valuation/**`
- `fundamental/workflow_orchestrator/application/*`
- `fundamental/workflow_orchestrator/interface/preview_projection_service.py`

## Detailed Per-File Plan

### Subdomain: artifacts_provenance
Current state:
- Only `interface/contracts.py` and `infrastructure/fundamental_artifact_repository.py` contain logic.
- `application/` and `domain/` are empty shells.

Plan:
- Remove empty layers (`application/`, `domain/`) or keep only if a near-term use-case is explicitly scheduled.
- Keep `FundamentalArtifactRepository` in infrastructure and contracts in interface.
- Confirm imports to `FinancialReportModel` remain in `financial_statements/interface/contracts.py`.

### Subdomain: core_valuation
Current state:
- Large domain surface (valuation engine, calculators, parameterization, policies, backtest).
- `application/` and `infrastructure/` are empty; interface has replay contracts only.
- Generic naming appears in `parameterization/model_builders/shared/*common*`.

Plan:
- Remove empty `application/` and `infrastructure/` layers or populate intentionally (but avoid empty shells).
- Consolidate or rename generic “common” modules to concrete owners:
  - `common_output_assembly_service.py` and `value_extraction_common_service.py` should either merge into their primary consumer or be renamed to specific roles (avoid “common”).
- Validate heavy-compute boundaries (Monte Carlo) remain off async event loop; if async calls exist, plan explicit boundary (`asyncio.to_thread`) and ensure performance gates remain.
- Review whether `replay_contracts.py` should remain in interface or move to a shared “replay” subpackage for cross-tool reuse (only if multiple subdomains consume it).

### Subdomain: financial_statements
Current state:
- Domain has only `report_semantics.py`; application empty.
- Infrastructure sec_xbrl is large and flat with multiple `*_utils` files.
- Interface contracts/types/parsers are clear but rely on domain constants.

Plan:
- Remove empty `application/` or define explicit use-cases if planned.
- Re-package `infrastructure/sec_xbrl` into clear subpackages by capability:
  - `fetch/` (fetcher, resolver, identity)
  - `extract/` (extractor, base_model_* builders)
  - `map/` (mappings, canonical mapping)
  - `quality/` (DQC gate, validation)
  - `cache/` (filing cache)
  - `providers/` (arelle engine)
- Eliminate generic file names by merging into owning services or renaming to explicit roles:
  - `report_factory_common_utils.py`, `factory_derived_utils.py`, `field_resolution_utils.py`.
- Audit whether any infrastructure models (e.g., `report_contracts.py`) should be marked explicitly as “extraction models” to avoid confusion with interface contracts (naming clarity).

### Subdomain: forward_signals
Current state:
- Domain has calibration + policy packages.
- Infrastructure sec_xbrl is large and flat; interface and application are empty.
- Forward signals propagate as `list[dict[str, object]]` across subdomains.

Plan:
- Introduce interface contracts for forward signals (typed schema, parser/serializer) to reduce `dict[str, object]` in application boundaries.
- Remove empty `application/` and `interface/` layers if no contracts are created (avoid empty shells).
- Re-package sec_xbrl pipeline into subpackages by stage:
  - `retrieval/` (filing loaders)
  - `filtering/` (fls filters, prefilter)
  - `matching/` (matchers)
  - `postprocess/` (postprocess, diagnostics)
- Rename generic or ambiguous files into stage-specific owners to improve navigability.

### Subdomain: market_data
Current state:
- Domain holds provider contracts and consensus logic.
- Application provides `MarketDataService` and `MarketSnapshot` (application-owned data model).
- Infrastructure holds provider adapters; interface is empty.

Plan:
- Decide canonical ownership of `MarketSnapshot`:
  - If it is a domain concept, move to `domain/`.
  - If it is an external boundary shape, move to `interface/contracts.py` and keep application orchestration separate.
- Move `MarketDataProvider` protocol to `application/ports.py` if it is an application boundary (align with architecture standard).
- Split `MarketDataService` into clear sub-owners if the file grows further: caching/retry, data assembly, consensus integration.
- Remove empty `interface/` if no external contracts remain.

### Subdomain: model_selection
Current state:
- Domain is cohesive (scoring, reasoning, signals, spec catalog).
- Application and infrastructure are empty; interface has report projection.
- `workflow_orchestrator/interface/preview_projection_service.py` depends on `model_selection.domain.financial_health_service`.

Plan:
- Remove empty `application/` and `infrastructure/` layers.
- Move `extract_latest_preview_metrics` or equivalent projection into `model_selection/interface/` to avoid interface → domain dependency from another subdomain. **Decision: use `model_selection/interface` as the canonical preview-metric projection owner.**
- Consider collapsing ultra-small domain services if they are single-purpose and always used together (reduce fragmentation).

### Subdomain: workflow_orchestrator
Current state:
- Application layer is large with flows, services, state readers/updates.
- Domain/infrastructure empty; interface contains preview formatting and projection.
- Interface uses `model_selection.domain` directly for preview metrics.

Plan:
- Remove empty `domain/` and `infrastructure/` layers.
- Re-package application into explicit subfolders:
  - `application/flows/` (financial_health_flow, model_selection_flow, valuation_flow)
  - `application/valuation/` (valuation_* services, replay contracts)
  - `application/state/` (state_readers, state_updates)
- Keep `workflow_orchestrator/interface` free of domain dependencies by consuming `model_selection/interface` for preview metrics (aligned decision).

### Subdomain: shared
Current state:
- Single contract (`TraceableField` provenance types).

Plan:
- Keep minimal; do not expand unless multiple subdomains share the same abstraction.

## Risk/Dependency Assessment
- Repackaging large `sec_xbrl` infrastructures risks import churn and subtle runtime breakage; must be done in phased slices with import hygiene gates.
- Moving forward-signal contracts into interface will require downstream updates in `workflow_orchestrator` and core valuation parameterization that currently accept untyped dicts.
- Removing empty layers is low risk but must be coupled with hygiene guards to prevent legacy imports.
- Rehoming preview metric extraction may affect interface formatting tests and orchestration preview outputs.

## Validation and Rollout Gates
- Lint: `ruff check` on touched modules.
- Tests (minimum):
  - Fundamental orchestration and preview: `tests/test_fundamental_*`
  - SEC XBRL pipelines: `tests/test_sec_xbrl_*`
  - Forward signals: `tests/test_sec_text_forward_signals*`
  - Core valuation performance gates: `tests/test_fundamental_monte_carlo_performance_gate.py`
- Import hygiene: `tests/test_fundamental_import_hygiene_guard.py`.
- For any contract move: run `tests/test_output_contract_serializers.py` and `tests/test_artifact_api_contract.py`.

## Assumptions/Open Questions
- Is it acceptable to remove empty layer directories across subdomains, or do you want to keep them as placeholders for uniformity?
- Should forward-signal contract schema be standardized now, or postponed to avoid churn in parameterization and artifacts?
- Do we want a shared `sec_xbrl` utility layer across `financial_statements` and `forward_signals`, or keep fully separated to preserve clean-cut boundaries?
- Should `MarketSnapshot` be treated as a domain model or boundary contract? This affects which layer owns the data class.
  - Decision logged: preview metric projection is owned by `model_selection/interface` and consumed by `workflow_orchestrator/interface`.
