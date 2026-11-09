# Issue #354 Progress

Date: 2026-11-10
Issue: [Workspace] Make Fundamental analysis evidence-first and remove manual valuation setup
Base commit: `6f8eaaff2af2cbeff8e7978cb3cc52b4a4452d74`
Branch: `codex/issue-354-workspace`

## Baseline

- The Workspace exposes `Start analysis`, `Start valuation`, and a required caller-owned valuation assumptions form.
- `Start analysis` sends no `valuation_request`, so the current Agent Core path publishes Fundamental facts-only output.
- Fundamental Service already returns automatic preparation, assumptions evidence, quality status, provenance, and Monte Carlo fields when the caller submits a compact `fundamental.v1` request.
- Valuation approval is currently surfaced in Activity even though Fundamental owns the valuation decision context.

## Planned delivery units

1. Replace the duplicate entry controls and remove the required caller-owned form.
2. Parse and render service-owned preparation, evidence, quality, provenance, and uncertainty in Fundamental.
3. Move approval and supported assumption edits into Fundamental while preserving service-owned calculations and digests.
4. Add focused frontend and browser acceptance evidence.

## Checkpoint: workspace review surface and degraded artifact

- Implemented the single automatic Workspace entry point and removed the required caller-owned valuation form.
- Added Fundamental-owned preparation review for model/policy identity, quality, formulas, evidence references, approval, and supported manual overrides.
- Added the canonical `override_prepared_valuation` caller operation and preserved service-owned override provenance and input digest changes.
- Added a typed Fundamental Service degraded artifact for upstream failures so the Fundamental tab reports code, retryability, and reason without inventing a valuation.
- Focused backend tests: `uv run pytest -q tests/agents/fundamental/test_fundamental_service_client.py tests/agents/fundamental/test_fundamental_service_cutover.py tests/agents/fundamental/test_service_request_producer.py` -> exit 0, 48 passed.
- Focused frontend tests: `npm test -- --run src/features/workspace/workspace-page.test.tsx src/features/workspace/outputs/fundamental-analysis/FundamentalReviewPanel.test.tsx src/types/agents/artifact-parsers.test.ts src/types/agents/fundamental-service-facts.test.ts` -> exit 0, 61 passed.
- Frontend `npm run typecheck` and `npm run lint` -> exit 0. `python3 scripts/architecture_guard.py` and `git diff --check` -> exit 0.
- Full backend pytest was attempted but collection remains blocked by existing duplicate `test_sql_repository` module names and missing `LLM_PROVIDER_SERVICE_URL` for unrelated debate/news/intent tests.

Status: WIP. Acceptance is not complete, the issue remains open, and no PR has been created.
