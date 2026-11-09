# Issue 352 acceptance record

This is a work-in-progress record. It does not mark #352 accepted or verified.

## Current checkpoint

- Issue: #352, the first incomplete issue in the requested sequence; OPEN.
- Branch: `codex/issue-352-auto-valuation` in its dedicated worktree.
- Baseline: `f250e4d3810feb7db342199874efe222500a79e0`, equal to `origin/main`.
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
| Keep history threshold provisional-only; abstain or degrade on missing, conflicting, structurally broken, or unresolved critical evidence. | Pending | #351 policy is merged; implement it in the service-owned preparation path and test the outcomes. |
| Retrieve aligned annual facts and trace every derived metric to fact IDs and formulas. | Pending | Extend the service facts contract and selection behavior. |
| Cover representative history, missingness, denominator, restatement, structural-break, and volatility cases. | Pending | Add behavior fixtures and tests at the service boundary. |
| Resolve market/policy inputs with as-of/source/version provenance; never silently substitute defaults. | Pending | Confirm permitted, wired sources; require an explicit reviewer decision or abstain when unavailable. |
| Keep Search/LLM and external forecasts out of the default path; handle transition evidence from the pinned filing only. | Pending | Update the service-owned request path and its callers. |
| Preserve automatic evidence and record manual override provenance and a new digest. | Pending | Implement and verify through the canonical service contract. |
| Run focused, architecture, Docker/service-backed, and exact-commit checks; merge a #352 PR and close the issue only after acceptance. | Pending | No implementation or runtime acceptance has run at this baseline. |

## Checks at baseline

| Check | Result |
| --- | --- |
| `git status --short --branch` in the #352 worktree | Exit 0; clean branch at the baseline commit. |
| `gh issue view` for #351 through #355 | Exit 0; #351 is closed and #352 is the first open issue in the fixed sequence. |
| `gh pr checks 358` | Required checks pass on PR head `0e63c0756ffcbddd5b914729c57d3cc482d1b338`; the merge commit is the #352 baseline. |
| #352 service or Docker tests | Not run; no #352 code has changed yet. |

## Next step

Ground the service and caller boundary, then record the canonical preparation contract and its acceptance tests before implementing valuation behavior. Recheck Compose ports immediately before startup. Each later checkpoint must name its exact commit, commands and results, remaining criteria, and next step.
