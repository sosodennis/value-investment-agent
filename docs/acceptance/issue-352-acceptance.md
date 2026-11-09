# Issue 352 acceptance record

This is a work-in-progress record. It does not mark #352 accepted or verified.

## Current checkpoint

- Issue: #352, the first incomplete issue in the requested sequence; OPEN.
- Branch: `codex/issue-352-auto-valuation` in its dedicated worktree.
- Baseline: `f250e4d3810feb7db342199874efe222500a79e0`, equal to `origin/main`.
- Latest branch checkpoint before this record: `46806aa3c08cd1a36f20b59fac91dfc90bc4db48` (documentation WIP; not accepted).
- Latest code checkpoint: `13ae21d178aad4650bc0e54e324c8662d85c71bb` (WIP; not accepted).
- #351: CLOSED by merged PR #358 at the baseline commit. Its supported history threshold remains null; the three-of-five candidate can produce at most a provisional result.
- #353, #354, and #355 remain OPEN and are not part of this checkpoint.
- #339 remains OPEN and owns SEC readiness/ingestion behavior. #352 must consume its pinned snapshot contract rather than duplicate acquisition. #350 remains an open blocker for an organization-owned full Agent pipeline; it does not make Search or LLM a dependency of this service path. #361 is the post-#352 replay follow-up.

## Baseline findings

- Fundamental Service currently selects facts from one immutable snapshot and calculates a caller-complete `ValuationInputV1`. Its facts request selects one point-in-time fact per normalized field; the normal Agent producer requests a narrow set and does not read aligned annual series.
- Initial valuation policies have no automatic assumptions. The accepted #351 matrix requires source, period, freshness, mapping, and quality evidence; missing critical values are unknown, never zero or placeholders.
- The target-state allows only `fcff_dcf` and `transition_fcff_dcf` for this profile. It requires five annual forecast periods, an explicit normalized sixth year, point-in-time WACC inputs, reviewed tax and debt assumptions, and explicit abstention when those inputs cannot be supported.
- The latest-five/at-least-three annual-history rule is unvalidated and cannot grant `verified`. #352 must preserve that policy and leave replay to #361.
- The service-backed Compose stack is `compose/verification/docker-compose.issue280-operations.yml`. No #352 containers are running. The dedicated project's candidate host ports 18652 and 18653 were not in use when checked; recheck before startup.

## Acceptance progress

| Criterion | Status | Evidence or remaining work |
| --- | --- | --- |
| Automatically prepare complete released-model inputs from pinned multi-period SEC facts and versioned policies. | Pending | Baseline path only selects latest facts and requires caller-supplied assumptions. |
| Keep history threshold provisional-only; abstain or degrade on missing, conflicting, structurally broken, or unresolved critical evidence. | Partial | The new pure selector keeps the unvalidated threshold provisional, rejects mapping conflicts, and abstains if the latest contiguous history is shorter than three years. It is not yet wired into SEC read or preparation paths. |
| Retrieve aligned annual facts and trace every derived metric to fact IDs and formulas. | Partial | The selector groups supplied duration and period-end instant facts; the canonical SEC facts read still needs a multi-period request/response and repository integration, and metric derivations are not implemented. |
| Cover representative history, missingness, denominator, restatement, structural-break, and volatility cases. | Pending | Add behavior fixtures and tests at the service boundary. |
| Resolve market/policy inputs with as-of/source/version provenance; never silently substitute defaults. | Pending | Confirm permitted, wired sources; require an explicit reviewer decision or abstain when unavailable. |
| Keep Search/LLM and external forecasts out of the default path; handle transition evidence from the pinned filing only. | Pending | Update the service-owned request path and its callers. |
| Preserve automatic evidence and record manual override provenance and a new digest. | Pending | Implement and verify through the canonical service contract. |
| Run focused, architecture, Docker/service-backed, and exact-commit checks; merge a #352 PR and close the issue only after acceptance. | Partial | Focused selector tests and Ruff passed on `13ae21d1`; architecture, service-backed Docker, full acceptance, PR, and merge remain pending. |

## Checks at baseline

| Check | Result |
| --- | --- |
| `git status --short --branch` in the #352 worktree | Exit 0; clean branch at the baseline commit. |
| `gh issue view` for #351 through #355 | Exit 0; #351 is closed and #352 is the first open issue in the fixed sequence. |
| `gh pr checks 358` | Required checks pass on PR head `0e63c0756ffcbddd5b914729c57d3cc482d1b338`; the merge commit is the #352 baseline. |
| #352 service or Docker tests | Not run; no #352 code has changed yet. |

## Annual history selector checkpoint

- Tested code commit: `13ae21d178aad4650bc0e54e324c8662d85c71bb`.
- Added a deterministic selector for verified, issuer/security-matched facts in the pinned snapshot. It aligns annual duration facts and period-end instant facts, respects fact and source availability, selects only the latest contiguous years, keeps an unvalidated threshold provisional, and rejects conflicting concepts, period shapes, unresolved amendment scope, and values.
- Missing required fields in the newest period stop the usable history at that gap; the selector abstains when fewer than three latest contiguous periods remain instead of falling back across the gap to older years.
- `cd fundamental-service && uv run --extra dev pytest -q tests/test_annual_history.py tests/test_fiscal_periods.py` — exit 0, 9 passed.
- `cd fundamental-service && uv run --with ruff ruff check src/fundamental_service/annual_history.py tests/test_annual_history.py` — exit 0.
- Commit hooks (whitespace, EOF, large-file, Ruff, Ruff format) — exit 0 on the commit.
- `LLM_PROVIDER_ENCRYPTION_KEY=issue352-config-check docker compose -p value-investment-agent-352-auto-valuation config --quiet` — exit 0; Compose parsing only, with an unset `FRED_API_KEY` warning. No containers were started.
- Remaining: connect multi-period SEC facts retrieval and release pinning; implement metric/formula provenance and service-owned assumption composition; wire all in-repository callers; exercise Docker health and the real service path. These tests use controlled fixtures and do not establish SEC/provider coverage.

## Contract design adjudication (WIP)

The cross-judge selected Candidate A as the contract base (23/25) and Candidate B as the source for exact fact-ID retrieval and incremental migration discipline (20/25). This is a design decision for #352, not an acceptance result or an API name/signature commitment.

- Fundamental Service owns one valuation-evidence preparation operation. Agent Core supplies identity, valuation-time intent, released-model intent, and the pinned snapshot/release reference; it does not choose field lists, fiscal windows, mappings, or conflict outcomes.
- A versioned requirements profile owns required fact roles, mappings, annual-period rules, unit/currency checks, criticality, and the current unvalidated threshold state. Its digest is included in the evidence/replay digest.
- The service reads exact fact IDs declared by the pinned snapshot/release manifest and validates issuer, release binding, digest, source/fact availability, and as-of time. Annual derivations must include duration facts and the opening/closing instant roles needed to support reinvestment and capital-bridge calculations.
- Return typed partial evidence with machine-readable missing, stale, conflict, structural-break, or unsupported reasons. Keep evidence quality separate from validation maturity; with `supported_history_threshold` null, a candidate three-of-five history can be no better than `provisional`.
- The current `resolve_annual_history` function is an interim pure selector. Its caller-supplied field lists must not become a second public preparation path; make selection profile-driven behind the canonical service operation as the contract is implemented.
- Reuse exact-ID reads internally, but migrate internal callers and tests together to the new pre-release contract. Do not add compatibility aliases, API upgrades, or a parallel legacy field-selection path. Keep any display-history branch out unless an existing facts-only caller needs it.
- Verify active release coverage for each required annual duration and opening/closing instant fact. A missing release fact cannot be manufactured by the contract: return the defined degraded/abstained outcome and record a blocker in the owning layer if the shared release contract is inadequate.
- Search, LLM, company guidance, analyst estimates, and current-period placeholders remain outside the default path.

## Verification on contract adjudication checkpoint

The checks below ran against code checkpoint `46806aa3c08cd1a36f20b59fac91dfc90bc4db48`; this record adds no executable code.

- `uv run --extra dev --project fundamental-service pytest fundamental-service/tests/test_annual_history.py fundamental-service/tests/test_fiscal_periods.py -q` — exit 0; 9 passed.
- `cd fundamental-service && uv run --with ruff ruff check src/fundamental_service/annual_history.py tests/test_annual_history.py` — exit 0.
- `git diff HEAD^ --check` — exit 0 before this documentation update.
- An initial Ruff invocation used the service's `dev` extra and exited 2 because Ruff is not declared there; the corrected `uv run --with ruff` invocation passed.
- Docker and service-backed acceptance were not run for this design-record checkpoint. No #352 Compose containers were started.

## Next step

Implement the release-bound requirements profile and exact-ID read path inside Fundamental Service, then prove active-release coverage for duration, opening, and closing facts before wiring metric derivation and automatic preparation. Extend the canonical SEC read contract without duplicating #339 acquisition, add service boundary tests for fact IDs/source availability/period alignment, and recheck Compose ports before startup. Keep selector tests as unit evidence only; service-backed acceptance and the remaining #352 criteria are pending. Each later checkpoint must name its exact commit, commands and results, remaining criteria, and next step.

## Canonical service boundary (WIP)

The automatic request path is service-owned. Agent Core remains responsible for
identity, #339 data readiness and snapshot pinning, model intent, configured
approval, and result projection. Once it has a pinned snapshot, it sends the
snapshot ID, release-manifest digest, and selected released model to the
Fundamental Service. It does not send caller-composed forecast/WACC
assumptions or a caller-selected fact list.

The service preparation operation loads the immutable snapshot and canonical
facts itself, selects aligned annual duration facts and period-end instant
facts, resolves the versioned model and policy, derives metrics and forecasts,
and returns either a typed prepared valuation or an explicit
requires-input/unsupported/abstained result with machine-readable reasons.
Each derived value retains its formula, periods, exact fact IDs, source
references, and policy version. The latest-five/at-least-three candidate stays
provisional while `supported_history_threshold` is null.

The calculation boundary must reconstruct preparation from the same pinned
snapshot and policy before calculating. Its canonical digest binds that
reconstruction; a caller-supplied digest alone is not evidence. Approval binds
to the reconstructed digest. Any supported manual adjustment is a separate
typed override with author, time, reason, and source evidence; the response
retains the original automatic assumption and computes a new digest.

Current source limitation: Treasury observations can be captured generically,
but the normal FCFF path does not resolve them. Damodaran rights and wiring,
lawful free point-in-time market capitalization, and a defensible marginal
debt-cost source are not established. The service must not fill these fields
with static defaults or current observations during replay. Until a permitted,
dated source or cited reviewer package is available, preparation must ask for
the required evidence or abstain. This limitation is part of acceptance; it
does not authorize Search/LLM, analyst estimates, or company guidance in the
default path.

The focused contract tests will cover snapshot/release binding, annual and
instant alignment, fact and formula provenance, deterministic reconstruction,
candidate-threshold status, explicit missing/conflict outcomes, and override
digest/provenance. Service-backed acceptance will exercise this same operation
through the isolated #352 Compose project; a successful fixture test alone
does not establish that real issuers have all required market evidence.
