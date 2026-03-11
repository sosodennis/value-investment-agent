# Ticket 08: shared Contracts Minimalism

## Requirement Breakdown
- Keep shared contracts minimal and strictly cross-subdomain.
- Prevent drift into a “misc” bucket.

## Technical Objectives and Strategy
- Validate that `TraceableField` and provenance types are truly shared.
- Avoid adding new shared abstractions unless at least two subdomains depend on them.

## Involved Files
- `finance-agent-core/src/agents/fundamental/shared/contracts/traceable.py`
- `finance-agent-core/src/agents/fundamental/shared/__init__.py`

## Slices

### Slice 1 (small): Shared Contract Audit
- Objective: verify all shared contracts are used by multiple subdomains.
- Entry: none.
- Exit: if any contract is single-use, move it back to the owning subdomain.
- Validation: `rg` usage check + relevant tests where moved.

### Slice 2 (small): Boundary Hygiene
- Objective: ensure no domain logic has leaked into shared contracts.
- Entry: slice 1 complete.
- Exit: shared contains only data contracts / types.
- Validation: `ruff check` on shared path; `tests/test_fundamental_import_hygiene_guard.py`.

## Risk/Dependency Assessment
- Low risk; changes are confined and mechanical.

## Validation and Rollout Gates
- Lint: `ruff check` on touched files.
- Tests: any tests covering provenance usage (e.g., `tests/test_report_contract_coercion.py`).
