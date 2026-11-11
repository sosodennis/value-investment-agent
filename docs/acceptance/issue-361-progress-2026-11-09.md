# Issue 361 progress checkpoint

This is a work-in-progress record, not acceptance or `VERIFIED` evidence.

## Current status (2026-11-10)

- Issue: #361 is OPEN and is the only active issue in this workstream.
- Issues #351 through #355 are CLOSED. PR #358 is merged; #351 is no longer
  blocked by this follow-up.
- PR #360 merged the fixed #359 SEC cohort report. PR #363 merged #352 and its
  Fundamental Service forecast composer.
- Branch: `codex/issue-361-replay-evidence`.
- Worktree: `/Users/denniswong/Desktop/Project/value-investment-agent-issue-361-replay-evidence`.
- `origin/main` at start: `485b2f59742454151faf56730e1e421e850cf978`.
- Ordinary merge commit retaining all existing #361 WIP commits:
  `a20cb0ef9b9536de44f8eb53f628a3fe8d092418`.
- Draft PR [#370](https://github.com/sosodennis/value-investment-agent/pull/370)
  is open at checkpoint `d3ee1d7a04362171c5215e9365151d556a9493e8`. Actions
  run `42770796965` passed 11 checks; `fundamental-release-gate` was skipped.
  The PR has no review decision and is not full replay acceptance.

The earlier sections below record evidence from their stated checkpoints.
Statements that #351 was open or #352 had not started describe the
2026-11-09 state and are not current status.

## Replay plan and completion predicate

The replay is complete only when the exact issue commit has deterministic
mapping, history, forecast, first-subsequent-label, rerun, and failure-retention
evidence; its report retains all 100 fixed issuers and source/mapping/model/
policy lineage; architecture, lint, type, Docker/service, and diff checks pass;
and the reviewed PR is merged and revalidated before #361 closes. The threshold
stays null and results stay provisional or abstained unless the replay evidence
supports a versioned threshold.

1. Preserve the checkpoint history, merge current main, and capture the
   pre-change verification baseline.
2. Audit the fixed cohort and encode a reviewed, issuer- and period-aware
   mapping manifest with stable input and artifact digests.
3. Replay each fixed decision through the #352 Fundamental Service composer;
   retain failures, incomplete labels, and model-specific accuracy evidence.
4. Run deterministic replay twice and verify unchanged artifacts, then run
   isolated #361 Docker/service acceptance and all code-quality gates.
5. Record exact-commit acceptance evidence, open the #361 PR, complete review
   and CI, merge, revalidate the merge commit, close #361, and clean up only
   #361-owned resources.

## SEC request and environment example

The `.env.example` in `origin/main` already defines `FUNDAMENTAL_SEC_USER_AGENT` with a non-operational contact placeholder. At the start of this checkpoint, the local `main` checkout was 13 commits behind and did not show that entry. It has since been fast-forwarded to `a2956589d4f01fb0754368406c00ac6f6928e568`. Keep the real contact in the ignored `.env`.

A read-only GET to `https://data.sec.gov/api/xbrl/companyfacts/CIK0001539778.json` used the configured User-Agent and returned HTTP 200. The response was 1,121,977 bytes with SHA-256 `6bfb258021d1976a47e06b42f3bebacbcef28d5b30fb54085a102cd839acd1c1`. The payload contains 109 raw `us-gaap:Revenues` fact entries, including three entries with accession `0001477932-16-007985`. These raw entries are source evidence only. They do not establish a universal mapping or a qualified historical series.

## Cohort result

The fixed 100-issuer cohort report was regenerated from its committed snapshots on base commit `a2956589d4f01fb0754368406c00ac6f6928e568`:

```sh
UV_CACHE_DIR=/tmp/.uv-cache uv run --project fundamental-service python -m fundamental_service.history_cohort report --manifest docs/acceptance/issue-359-sec-cohort-v1/capture_manifest.json --output /tmp/issue361-cohort-report.json
```

The uncompressed report SHA-256 is `1a3995af98d3fda2166873c25f0ba981d89016ae6f6f98dc4515a077eac41b9f`, matching the existing report evidence. Its status remains `underpowered`. Both models retain 100 issuers in the denominator, with 0 candidate-eligible issuers, 0 complete first-subsequent labels, and 0 issuers with three revenue periods under the report's current single-concept mapping. A next original filing is available for 91 issuers, but none has a complete label under the current measured field set. Forecast accuracy remains unmeasured because no historical Fundamental Service forecasts exist. The report keeps `supported_history_threshold` null.

The candidate rule remains three complete periods in the latest five original annual filings. It is unvalidated and cannot mark a result `verified`. Keep qualifying outputs provisional; abstain when required facts are missing or conflict. Do not treat `us-gaap:Revenues` as a general alias until its issuer, period, unit, scope, and conflict behavior receive mapping review.

## Service boundary finding

`ForecastAssumptionsV1` accepts caller-supplied growth, margin, and reinvestment series. `ValuationInputV1` requires explicit FCFF forecast, WACC, terminal growth, capital bridge, and trace assumptions. The calculate endpoints execute those supplied inputs. `/v1/valuation/replay` replays a previously recorded calculation; it does not create a forecast from historical facts.

At this 2026-11-09 checkpoint, #352's composer had not yet merged, so this
work did not generate forecasts or change #351 acceptance. PR #363 has since
merged the service-owned composer. #361 must now call that operation and
preserve its explicit blocked outcomes; it must not add a second forecast
policy.

## Verification on the base and first checkpoint commits

The SEC request ran on base commit `a2956589d4f01fb0754368406c00ac6f6928e568`. The test suite, architecture guard, diff check, and cohort report passed on that base and were rerun on first checkpoint commit `f58d26e0`.

| Check | Result |
| --- | --- |
| SEC Company Facts GET for CIK `0001539778` | HTTP 200; response hash recorded above; no contact value in output. |
| Focused Fundamental Service cohort, sufficiency, calibration, and fact tests | `50 passed`. |
| `python3 scripts/architecture_guard.py` | Exit 0; no boundary violations. |
| `git diff --check` | Exit 0; worktree was clean before this note. |
| Fixed cohort report regeneration | Exit 0; report hash matched existing evidence; status `underpowered`. |
| Docker or service-backed forecast replay | Not run. The current service has no historical forecast producer to exercise. |

The exact test command was:

```sh
UV_CACHE_DIR=/tmp/.uv-cache uv run --extra dev --project fundamental-service pytest fundamental-service/tests/test_history_cohort.py fundamental-service/tests/test_history_sufficiency_report.py fundamental-service/tests/test_calibration.py fundamental-service/tests/test_facts.py -q
```

## Sequence decision

The accepted sequence preserved #351 -> #352 -> #361. #351 and #352 are now
closed, and #352 provides the canonical Fundamental Service composer. The
three-of-five history rule remains unvalidated and cannot produce `verified`
results. #361 must replay through the service composer, leave
`supported_history_threshold` null unless evidence supports promotion, and
keep affected results provisional or abstained. The #351 acceptance and PR #358
are historical records and are not being changed by this follow-up.

## Revenue candidate audit checkpoint

The first SEC Company Facts candidate audit captured and retained responses for
all 100 preselected issuer clusters. Its immutable evidence is under
`docs/acceptance/issue-361-sec-mapping-v1/`; the evidence manifest SHA-256 is
`cca2e1ea8fd1220f952f13c8c5feb2a841a6f1d04b1dcd578d83802e060dcae4`, bound to
the existing #359 cohort manifest SHA-256 above. No issuer was replaced. The
SEC response hashes and per-issuer evidence hashes are in that manifest.

The first report is invalid for coverage interpretation. It searched concept
names and labels for `revenue|sales`, producing 242 candidates and reporting
74/100 clusters with one concept covering three of five periods. That result
includes non-revenue concepts: `CostOfRevenue` alone produced 13 apparent
three-of-five matches, and `ProceedsFromSaleOfAvailableForSaleSecuritiesDebt`
produced two. The invalid report SHA-256 is
`1fdb48538af1687bb8481b3108e2cc6474ffff635673e3e83afda4d70f546703`. Treat
the 74/100 figure as withdrawn; it is not a coverage estimate or threshold
evidence. The source response subsets remain available to regenerate a
corrected candidate report without additional SEC requests.

The existing offline tests for the initial audit passed three cases:

```sh
uv run --extra dev --project fundamental-service pytest fundamental-service/tests/test_history_mapping_audit.py -q
```

This checkpoint does not approve a concept mapping. Exact total-revenue tags
will be used only to generate a narrower candidate list; issuer, period, unit,
and scope review is still required. The report remains separate from
Fundamental Service's valuation forecast policy, which is not implemented.
No historical Fundamental Service forecasts, complete model-field OOS labels,
or forecast-error results existed at this 2026-11-09 checkpoint. The supported
threshold was null. At that time #351 was open and #352 was unstarted. No Docker
or service-backed acceptance ran for that checkpoint; it was an offline
evidence-capture/reporting slice.

## First allowlist attempt: incomplete WIP

The first implementation changed live SEC payload extraction to keep only the
three exact total-revenue candidate tags, and its four focused tests passed.
The full report rerun still read the older saved candidate subsets directly,
so it retained 242 candidate concepts and the same 74/100 screen. The command
exited 0, but output inspection showed the candidate filter had not reached the
reporting path. That report SHA-256 is
`bfdff48af7fb86674c681e3db0bddce47998d7a2183eafb88e3a799a63630e1f`; it is also
invalid and is not acceptance evidence. Next, apply one classifier to both
fresh Company Facts payloads and previously captured evidence, then add a
regression test at the report reconstruction boundary.

## Narrowed candidate report v2

The candidate rule now uses the exact US-GAAP tags
`RevenueFromContractWithCustomerExcludingAssessedTax`, `Revenues`, and
`SalesRevenueNet`. The same allowlist is applied when capturing new Company
Facts and when rebuilding reports from saved evidence, so old broad-keyword
snapshots cannot reintroduce component, proceeds, or segment concepts into the
screen. The selected cohort and original decision accessions are unchanged.

The corrected report is `docs/acceptance/issue-361-sec-mapping-v1/report.json.gz`.
Its compressed SHA-256 is
`8d638e31e069c4f05dc991a40fdc92b990318a236ca174a687ddcacb121b813a`; its
uncompressed JSON SHA-256 is
`508e721bfaa564eeb08a2f17a37e33405a346b78a11f7b870f4c4f9d855bb0ed`. The
source evidence manifest is unchanged at
`cca2e1ea8fd1220f952f13c8c5feb2a841a6f1d04b1dcd578d83802e060dcae4`. The
report records 100 selected and captured clusters, 56/100 with at least one
listed tag appearing in three of five periods, and zero excluded component or
proceeds tags in its candidate list. The 56/100 is an unreviewed candidate-tag
screen, not canonical coverage, an upper bound, a supported threshold, or a
verified eligibility result. It does not resolve issuer-period mapping or
source-scope review.

The report command exited 0 twice on the same evidence. The first run wrote the
artifact (`wrote: true`); the second was idempotent (`wrote: false`) and
returned the same uncompressed report hash. Checks before the next checkpoint
commit passed:

```sh
uv run --extra dev --project fundamental-service pytest fundamental-service/tests/test_history_mapping_audit.py fundamental-service/tests/test_history_cohort.py fundamental-service/tests/test_history_sufficiency_report.py fundamental-service/tests/test_calibration.py fundamental-service/tests/test_facts.py -q
python3 scripts/architecture_guard.py
git diff --check
```

The test command passed 54 tests, the architecture guard passed, and the diff
check passed. No Docker stack or service-backed valuation end-to-end check ran:
the report is offline, and the service had no historical forecast producer at
that checkpoint. Historical Fundamental Service forecasts, complete model-field
out-of-sample labels, and forecast-error results remain absent. The supported
history threshold remains null. At the time of this 2026-11-09 checkpoint,
#351 was still open and #352 had not started; both are now CLOSED.
