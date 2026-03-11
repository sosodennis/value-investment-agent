# Ticket 03: financial_statements Quality and Cohesion

## Requirement Breakdown
- Reduce fragmentation and flattening in `infrastructure/sec_xbrl` by capability grouping.
- Remove empty `application/` layer.
- Remove generic `*_utils` naming.

## Technical Objectives and Strategy
- Keep `interface/` as canonical report contracts and parsers.
- Keep `domain/` for deterministic semantics only.
- Re-package `sec_xbrl` by pipeline stage to improve cohesion and navigability.

## Involved Files
- `finance-agent-core/src/agents/fundamental/financial_statements/application/__init__.py`
- `finance-agent-core/src/agents/fundamental/financial_statements/infrastructure/sec_xbrl/*`
- `finance-agent-core/src/agents/fundamental/financial_statements/interface/*`
- `finance-agent-core/src/agents/fundamental/financial_statements/domain/report_semantics.py`

## Slices

### Slice 1 (small): Remove Empty Layer
- Objective: delete empty `application/` package.
- Entry: no imports depend on it.
- Exit: directory removed; hygiene guard updated if needed.
- Validation: `ruff check` on touched paths; `tests/test_fundamental_import_hygiene_guard.py`.

### Slice 2 (medium): Re-package `sec_xbrl` by Capability
- Objective: create subpackages (e.g., `fetch/`, `extract/`, `map/`, `quality/`, `cache/`, `providers/`) and move modules accordingly.
- Entry: map each existing module to a stage.
- Exit: imports updated; no cross-stage circulars; naming consistent with owner role.
- Validation: `tests/test_sec_xbrl_*`, `tests/test_sec_text_filing_section_selector.py`.

### Slice 3 (small): Eliminate Generic `*_utils` Files
- Objective: merge or rename `report_factory_common_utils.py`, `factory_derived_utils.py`, `field_resolution_utils.py` into specific owners.
- Entry: slice 2 complete.
- Exit: no `*utils*` files remain in mature paths.
- Validation: `tests/test_sec_xbrl_financial_payload_service.py`, `tests/test_sec_xbrl_mapping_fallbacks.py`.

### Slice 4 (small): Contract Clarity Audit
- Objective: ensure extraction-time models (`report_contracts.py`) are clearly internal and distinct from interface contracts.
- Entry: slice 3 complete.
- Exit: naming/docstrings updated if needed; no interface leakage.
- Validation: `tests/test_report_contract_coercion.py`.

## Risk/Dependency Assessment
- High risk of import churn due to large `sec_xbrl` module count.
- Use phased moves and run tests after each slice.

## Validation and Rollout Gates
- Lint: `ruff check` on touched files.
- Tests: `tests/test_sec_xbrl_*`, `tests/test_report_contract_coercion.py`, `tests/test_fundamental_interface_parsers.py`.

## Assumptions/Open Questions
- No cross-subdomain consolidation of `sec_xbrl` is desired (clean-cut boundary preserved).
