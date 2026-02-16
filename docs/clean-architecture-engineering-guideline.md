# Clean Architecture Engineering Guideline
Date: 2026-02-12
Scope: Monorepo (`finance-agent-core` + `frontend`)
Policy: Zero compatibility, fail-fast, contract-first.

This is the top-level rulebook. Detailed implementation rules are split into:
1. `docs/backend-guideline.md`
2. `docs/frontend-guideline.md`

## 1. Canonical Rule Hierarchy

1. This file defines cross-stack mandatory rules.
2. `docs/backend-guideline.md` defines backend-specific mandatory rules.
3. `docs/frontend-guideline.md` defines frontend-specific mandatory rules.
4. Historical plan/progress docs are non-normative (audit trace only).

## 2. Mandatory Architecture

Dependency direction is strict:
1. `Domain <- Application <- Interface <- Infrastructure`

Layer ownership:
1. Domain: valuation rules, invariants, provenance semantics.
2. Application: workflow orchestration and use cases.
3. Interface: contracts, parsers, mappers, adapters, API/SSE schemas.
4. Infrastructure: DB, persistence, external APIs, LLM providers.

Hard rules:
1. Application layer cannot perform runtime shape guessing for external payloads.
2. Cross-boundary payloads must be validated at boundaries, not inside business flow.
3. Contract breaks are allowed only as atomic backend+frontend changes in one PR.

## 3. Cross-Stack Contract Policy

1. Every cross-boundary payload must have explicit `kind` + `version`.
2. Backend is source of truth for API schema and contract constants.
3. Frontend consumes generated contracts, then runtime parser, then adapter/view model.
4. No silent compatibility branch for old payload shapes.

## 4. Forbidden Patterns (Global)

1. Compatibility fallback for legacy payload shape.
2. Duck typing dispatch (`hasattr`, list/dict guessing) in core flow.
3. `Any` in backend core/runtime contract path and frontend runtime contract path.
4. UI components parsing raw backend payload directly.

## 5. Standard Change Workflow

1. Update contract/constants first.
2. Update backend producer + backend parser/port.
3. Regenerate contracts when API changed:
   - `bash scripts/generate-contracts.sh`
4. Update frontend parser/adapter/view model in same PR.
5. Update tests and fixtures in same PR.
6. Update docs/checklists in same PR.

## 6. Mandatory Quality Gates

Backend:
1. `uv run --project finance-agent-core python -m ruff check <touched-files>`
2. `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_protocol.py finance-agent-core/tests/test_mappers.py finance-agent-core/tests/test_news_mapper.py finance-agent-core/tests/test_debate_mapper.py -q`
3. Contract/API suites when artifact/API changed.

Frontend:
1. `npm run lint`
2. `npm run typecheck`
3. `npm run test -- --run`

## 7. PR Acceptance Checklist (Cross-Stack)

1. No compatibility/fallback branch introduced.
2. No `Any` introduced in runtime contract path.
3. Contract, parser/port, adapter, and tests updated together.
4. Generated contract artifacts are up to date when schema changed.
5. Docs updated (at least one of the three guideline docs if behavior/policy changed).

## 8. Document Lifecycle

Canonical (active):
1. `docs/clean-architecture-engineering-guideline.md`
2. `docs/backend-guideline.md`
3. `docs/frontend-guideline.md`
4. `docs/agent-layer-responsibility-and-naming-guideline.md`
5. `docs/README.md` (document authority index)

Historical (reference only, may contain phased context):
1. `docs/clean-architecture-agent-workflow-blueprint.md`
2. `docs/fullstack-change-control-playbook.md`
3. `docs/archive/monorepo-contract-upgrade-plan.md`
4. `docs/archive/monorepo-contract-upgrade-progress.md`
5. `docs/archive/deep-refactor-master-plan-2026-02-13.md`
6. `docs/archive/deep-refactor-progress-2026-02-13.md`
