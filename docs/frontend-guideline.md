# Frontend Guideline
Date: 2026-02-12
Scope: `frontend`
Policy: Parser-first, view-model-only UI, zero compatibility fallback.

## 1. Mandatory Frontend Data Flow

Every runtime path must follow:
1. `Generated Contract Types` ->
2. `Boundary Runtime Parser` ->
3. `Domain/View Model Adapter` ->
4. `UI Component`

Rules:
1. Hooks and components must not consume raw API/SSE/artifact payloads directly.
2. UI components render view models only.
3. Unknown/unsafe payload types are allowed only at parser boundary.

## 2. Runtime Contract Boundaries

1. REST/SSE parser boundary:
   - `frontend/src/types/protocol.ts`
2. Artifact envelope parser boundary:
   - `frontend/src/types/agents/artifact-envelope-parser.ts`
3. Domain artifact parsers:
   - `frontend/src/types/agents/artifact-parsers.ts`
4. Output adapter/view model boundary:
   - `frontend/src/types/agents/output-adapter.ts`

## 3. Current Canonical Frontend Pattern

1. Agent output routing is by `output.kind` (not by agent id shape guessing).
2. `useArtifact` requires parser injection; no unparsed artifact usage.
3. Preview parsers are domain-split modules (`fundamental/news/debate/technical`).
4. `preview.ts` keeps shared preview types/guards only.

## 4. Type and Safety Rules

1. No runtime `as` assertion for boundary payload decode.
2. No `Any` in runtime contract path.
3. No component-level defensive parsing for backend payload shape.
4. Parser drift must throw explicit errors (fail-fast), not silently downgrade.

## 5. Standard Frontend Change Recipes

## 5.1 Display New Output

1. Ensure backend output contract has `kind/version/preview/reference`.
2. Add/extend domain parser.
3. Add/extend output adapter mapping.
4. Update UI component props to typed view model only.
5. Add parser/adapter tests.

## 5.2 Add New API/SSE Response Consumer

1. Add parser function in `protocol.ts` or agent parser module.
2. Use parser in hook before state update.
3. Add contract tests for valid and invalid payload.

## 5.3 Remove Field/Class/Output

1. Remove parser branch + adapter branch + UI usage in same PR.
2. Remove fixtures/tests for old shape in same PR.
3. No compatibility branch.

## 6. Frontend Quality Gates

1. `npm run lint`
2. `npm run typecheck`
3. `npm run test -- --run`

When backend API schema changed:
1. Run `bash scripts/generate-contracts.sh`
2. Commit both generated files:
   - `contracts/openapi.json`
   - `frontend/src/types/generated/api-contract.ts`

## 7. Frontend Anti-Patterns

1. `fetch(...).json()` result flowing into UI without parser.
2. Directly reading `output.preview` inside components and guessing shape.
3. Using generic fallback rendering to hide parser failures.
4. Keeping old parser branches after breaking contract cutover.

## 8. Detailed Reference

1. `docs/fullstack-change-control-playbook.md`
2. `docs/archive/monorepo-contract-upgrade-progress.md`
