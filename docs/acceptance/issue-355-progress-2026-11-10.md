# Issue #355 progress: opt-in forward-evidence reference

Status: WIP checkpoint. This document records the implementation boundary and
the evidence still required before issue acceptance.

## Current state

- Branch: `codex/issue-355-forward-reference`
- Base commit: `e761e13577fb0e50cf611edd0ee2386e90ed360a`
- Normal Fundamental valuation remains the only default path. Search and LLM
  calls are not part of the normal request flow.
- The optional reference will use an explicit Fundamental action route. Agent
  Core owns request orchestration and provider calls; Fundamental Service owns
  claim validation, quality disposition, source/licensing provenance, and
  application of a selected value.

## Checkpoint `10d9ff3c`

This checkpoint records the public-entrypoint and resource-boundary repair on
the exact commit `10d9ff3c` (`checkpoint(#355): enforce fundamental entrypoint
boundaries`). The API now imports the Fundamental public entrypoint; the route
is built from an injected service factory; capability consumers use the
forward-evidence facade; and LLM principal/context access uses the
`llm_provider.entrypoint` contract.

The representative opt-in fixture measured one search query, one retained
discovery result, zero source fetches, one structured LLM call, and a 15,000 ms
request budget. The policy bounds are five results per query, 120,000 source
bytes, eight extracted claims, and 15,000 ms. These are recorded fixture
measurements and a bounded policy, not production enablement approval.

Checks run against `10d9ff3c`:

| Check | Result |
| --- | --- |
| `python3 scripts/architecture_guard.py` | exit 0; no boundary violations |
| `uv run --project finance-agent-core ruff check ...` | exit 0 |
| `PYTHONPATH=finance-agent-core uv run --project finance-agent-core python -c 'from src.agents.fundamental.entrypoint import fundamental_forward_evidence_router; ...'` | exit 0 |
| `PYTHONPATH=finance-agent-core uv run --project finance-agent-core python -c 'import api.server; ...'` | exit 0 |
| Agent Core focused pytest | exit 0; 25 passed |
| Fundamental Service focused pytest | exit 0; 63 passed |
| frontend `npm run typecheck` | exit 0 |
| frontend focused Vitest | exit 0; 28 passed |
| `bash scripts/generate-contracts.sh` | exit 0; generated artifacts synchronized |
| `docker compose --env-file .env.example config --quiet` | exit 0 |
| `git diff --check` and staged commit checks | exit 0 |

Docker service-backed acceptance, real browser interaction, exact-commit CI,
PR review, and merge to `main` remain outstanding. The issue is still WIP and
must not be marked verified or closed.

## Planned contract

1. A reference request identifies the issuer, model, material evidence field,
   and the automatic preparation digest. It is rejected unless the caller has
   explicitly opted in.
2. The response is a separate forward-looking evidence layer. Each numeric
   claim includes the issuer, metric, value, unit, fiscal period, publication
   and retrieval timestamps, source identity, retained passage, content hash,
   extraction method, quality/conflict status, and license metadata.
3. Unsupported, stale, mismatched-period, conflicting, or unlicensed claims
   are excluded or surfaced with a typed reason. Search results and LLM output
   alone are never treated as evidence.
4. Research does not change a valuation. Applying one claim calls the existing
   Fundamental override path with the automatic preparation and a manual
   provenance record that retains the selected reference. A new input digest
   and recalculation are required.

## Checks still required

- Contract and domain tests for valid claims, rejection reasons, conflicts,
  licensing, freshness, and digest-bound application.
- Agent Core tests proving no optional-provider call on the normal path,
  explicit opt-in orchestration, provider failure, and bounded resource use.
- Browser tests for the explicit Fundamental action, evidence display, and
  selected application.
- Isolated Docker/service-backed acceptance with the #355 Compose project,
  followed by exact-commit CI and PR evidence.

## Known limitation

No production provider calls are enabled by default. Resource budgets remain a
measured acceptance item; this checkpoint does not claim #355 is verified.

## Browser acceptance checkpoint

The issue-scoped browser session used the disposable account
`issue355-20261109235229-4ca4df@staging.invalid` against the stack on
`http://127.0.0.1:18881`.

- Run `2f8dd84d-2076-4ef3-b776-89c14cd1f487` completed, but Fundamental Service
  returned `IDENTITY_RESOLUTION_UNAVAILABLE` because the first runtime omitted
  `FUNDAMENTAL_SEC_USER_AGENT`.
- After injecting the existing local SEC contact into the issue-scoped
  Fundamental container, run `48fb7db2-7282-4a33-bddd-201c37b56db0` returned
  `IDENTITY_RESOLUTION_NOT_AUTHORIZED`; the service was still authorizing only
  `local-development`, while the disposable account used organization
  `166b258e-3137-4f78-91a4-f9a064de676b`.
- The same real Workspace baseline showed `Search news`, `Select relevant
  articles`, `Fetch article content`, and downstream news/LLM activity before
  any explicit forward-evidence action. GitHub issue #355 was subsequently
  revised at `2026-11-10T00:06:31Z` to state that broader Workspace News/Debate
  provider calls are outside this criterion. The browser check was therefore
  scoped to the Fundamental preparation path and proved that the optional
  forward-evidence route is only exercised after the explicit action.

These runs are historical diagnostic evidence. The latest implementation
checkpoint below records the passing browser result; no PR or issue closure is
authorized until the exact commit, review, CI, and merge gates are complete.

## Latest implementation checkpoint `79c3e774`

The browser acceptance run exposed a request-boundary defect: the frontend sent
the canonical JSON value `2026-11-10T00:55:00Z`, while the strict
`ForwardEvidenceResearchRequest` model rejected the string before the route
handler ran. The boundary validator now accepts ISO-8601/RFC3339 JSON strings,
requires timezone information, and normalizes accepted values to UTC. The
strictness of the remaining request contract is unchanged.

Checks run against `79c3e774`:

| Check | Result |
| --- | --- |
| Agent Core forward-evidence tests | exit 0; 7 passed |
| Fundamental Service forward-evidence tests | exit 0; 6 passed |
| Frontend focused tests | exit 0; 39 passed |
| Frontend `npm run typecheck` | exit 0 |
| Ruff on changed Python files | exit 0 |
| `python3 scripts/architecture_guard.py` | exit 0 |
| `bash scripts/generate-contracts.sh` | exit 0; no generated contract diff |
| `git diff --check` and commit hooks | exit 0 |

The issue-scoped Compose stacks were rebuilt from this fix. Application
`http://127.0.0.1:18880/health` and Fundamental Service
`http://127.0.0.1:18890/readyz` both returned successfully. The application
project is `value-investment-agent-355-forward-reference`; the Fundamental
project is `value-investment-agent-355-forward-reference-fundamental`.

The real Workspace run used browser tab `8`, run
`578f54e1-a079-4d61-8038-4eb2457c3d1a`, and artifact
`9346d290-ce03-48bc-ad4b-21348bc401a`. The explicit **Research evidence**
action changed from HTTP `422` to HTTP `200 OK`. The typed result was
`unavailable` with reason `LLM_PROVIDER_FAILURE`; it stated that no claim was
eligible to change the baseline and reported one search query, five results,
and one LLM call. Backend logs show the search request succeeded and the LLM
provider returned `502`, which the optional route converted into the typed
non-blocking result. The default valuation remained unchanged.

Provider-backed successful claim extraction and application are covered by the
unit and service tests. They were not live-browser verified because this
acceptance runtime has no usable provider credential. That limitation does not
block the required provider-failure behavior, but it remains an explicit
unverified path until a separately authorized provider runtime is available.

The feature acceptance criteria are verified against checkpoint
`4ba8a27462242cd609016a8ebd26bc9eeaeaeade`. The full history checkout
(`fetch-depth: 0`) is now specifically on `contract-policy`; unrelated jobs
remain unchanged. All 11 required PR checks passed on this exact checkpoint,
including the ancestry policy gate. The manifest is rebound to this checkpoint
and will be rechecked locally before PR #368 returns to ready. The issue
remains OPEN until merge, merge-commit verification, issue closure, and
cleanup.
