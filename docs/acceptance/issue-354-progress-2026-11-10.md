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

## Checkpoint: fix transition ingestion contract boundary

The browser-backed run reached workflow completion but produced no
`fundamental_analysis.output`. The backend log showed identity resolution
returning HTTP 200 followed by `POST /v1/data/ingestions` returning HTTP 400.
The failing request was the default `dcf_growth` transition FCFF path. Its
canonical evidence set contains 33 fields (`_BASE_REQUIRED_FIELDS` plus
`filed_operating_evidence`), while `SecIngestionRequestV1` capped both
`required_fields` and `mappings` at 32. The request was rejected at the
service schema boundary before SEC acquisition ran.

Checkpoint commit: `649502491c10c5f81fe2b16714616611cc313942`

The service-owned contract now accepts up to 64 required fields and mappings,
with a regression test that validates a 33-field transition-sized request.
The caller contract remains unchanged and no valuation formula or policy moved
into Agent Core.

Validation for this exact commit:

- `uv run --extra dev pytest -q tests/test_contracts.py tests/test_source_acquisition.py` (Fundamental service, exit 0; 21 passed)
- `uv run pytest -q tests/agents/fundamental/test_service_request_producer.py tests/agents/fundamental/test_fundamental_service_client.py tests/agents/fundamental/test_fundamental_service_cutover.py` (Agent Core, exit 0; 48 passed)
- `python3 scripts/architecture_guard.py` (exit 0)
- `git diff --check` (exit 0)

Next step: rebuild the isolated #354 Fundamental service and rerun the
browser acceptance to verify that ingestion, preparation review, evidence,
quality, provenance, and approval are rendered in the Fundamental tab.

## Checkpoint: MSFT service control and parser resource blocker

The isolated Fundamental service was rebuilt from the #354 verification
configuration with the approved SEC User-Agent already present in the runtime
environment. The service-owned PostgreSQL database retained the 33 immutable
`sec-us-gaap-v1-*` mappings provisioned for this issue.

- A signed MSFT identity request for organization
  `07539eaf-4b6d-46cc-a91b-9763fe182339` returned HTTP 200 and resolved CIK
  `0000789019`, `MICROSOFT CORP`, US-GAAP/USD, and ticker/share class `MSFT`.
- A minimal signed producer-shaped ingestion request for the pinned accession
  `0000950170-24-087843`, required field `revenue`, and mapping
  `sec-us-gaap-v1-revenue` returned HTTP 200 `status=created` with
  `quality_status=verified`. The immutable snapshot was
  `snapshot-98727c1cf8636f4decad0cfe1bb6b3fb` with manifest digest
  `f40c5a145b601724749d136ca38ac7636dd24dd12cf85cd0915dd8c5088a9619` and
  correlation `issue-354-msft-ingestion-control-2`.
- A service-owned multi-field control using the same accession and the
  8/16/32-field prefixes returned the redacted HTTP 400
  `invalid_request` response. The exact service logs recorded the same
  response for correlations `issue-354-msft-prefix-8-20261110`,
  `issue-354-msft-prefix-16-20261110`, and
  `issue-354-msft-prefix-32-20261110`.
- After the bounded multi-field probes, Docker reported
  `OOMKilled=true` for `value-investment-agent-354-fundamental-fundamental-service-1`.
  The service was restarted with `docker start` using the existing isolated
  container configuration and returned to healthy readiness; PostgreSQL and
  the published mapping records were preserved.
- No partial snapshot or canonical fact publication was accepted for the
  failed multi-field request. The normal #354 automatic path therefore still
  cannot be marked verified because it has not completed preparation, evidence
  review, approval, and calculation against a full producer-shaped request.

This exposes a new owning-layer blocker: [#365](https://github.com/sosodennis/value-investment-agent/issues/365)
tracks bounded SEC parser memory/concurrency and a stable typed resource
failure. #354 remains WIP and open until #365 is resolved, the exact-head
service-backed replay passes, and the workspace acceptance is rerun.
