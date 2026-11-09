# Issue 359 progress checkpoint

This is a work-in-progress record, not acceptance or `VERIFIED` evidence.

## Current state

- Issue: #359, the blocker for #351's representative history-threshold evidence.
- State: OPEN; no threshold has been measured or approved.
- Branch: `codex/issue-359-sec-history-cohort`.
- Worktree: `/Users/denniswong/.codex/worktrees/value-investment-agent-issue-359-sec-history-cohort`.
- Base: `origin/main` at `6ed0031f38b05740ae2fb47b7fbfe607963d92fa`.
- Pull request: none yet.
- The local `.env` in the main checkout has an identifiable SEC User-Agent. Its
  value is not stored in this repository or printed in request logs.

## Live SEC access and sampling protocol

A read-only request to `data.sec.gov/submissions/CIK0000320193.json` returned
HTTP 200, CIK `0000320193`, Apple Inc., and 1,006 recent filing entries. This
proves endpoint access only; it is not cohort evidence.

The following historical sources were downloaded from SEC over HTTPS:

| Source | HTTP | Bytes | SHA-256 |
| --- | ---: | ---: | --- |
| SEC 2016 Q1 `master.idx` | 200 | 27,657,710 | `43ccb67ed90ad4229b02b99094846a291c6d1672eb25a1ee89dcb0636c2a264e` |
| SEC 2016 Q1 Financial Statement Data Set | 200 | 95,470,843 | `5c89a6badede1b47ab540913c7484795c7fc4c2a4672ac601b34b8c0afe5a698` |

The master index contains 5,462 original 10-K rows across 5,338 CIKs. The
matched XBRL data set contains 4,494 CIKs, of which 3,999 report `US` as their
filing-time incorporation country. The frame excludes 844 index CIKs without
a matching data-set row and 495 matched CIKs with non-US or unknown
incorporation country. These exclusions are explicit; the cohort claim is
limited to the declared US-incorporated XBRL filing population.

`issue-359-cohort-protocol-v1.json` predeclares one decision filing per CIK,
filing-time SIC strata, deterministic proportional sampling of 100 issuers,
point-in-time input selection, first-subsequent-original-10-K labels, the
three-of-five candidate rule, and issuer-clustered uncertainty. Industry
estimates remain descriptive without 100 issuers in a stratum. Forecast error
is not measurable without historical Fundamental Service forecasts; no
forecast-performance claim is authorized by this protocol.

## Verification on this checkpoint

| Check | Result |
| --- | --- |
| Parse `issue-359-cohort-protocol-v1.json` with Python's JSON parser | Exit 0; protocol schema and predeclared sample size validated. |
| Reconcile SEC source hashes and master-index/data-set frame counts | Exit 0; 5,462 original 10-K rows, 5,338 index CIKs, 4,494 matched data-set CIKs, 3,999 US-incorporated CIKs, 844 unmatched exclusions, and 495 non-US/unknown exclusions matched the protocol. |
| `git diff --check` | Exit 0. |
| Company Facts and submissions cohort capture | Not run |
| Model-field coverage and first-subsequent labels | Not run |

No Docker Compose project is needed for this data-acquisition and report slice.

## Next steps

1. Verify and commit the predeclared protocol checkpoint.
2. Implement deterministic frame selection, SEC snapshot capture, and an
   offline report with explicit exclusions and immutable evidence hashes.
3. Capture the selected cohort using the local User-Agent without exposing its
   value; retain retrieval failures in the denominator.
4. Run temporal-ordering, original-versus-amendment, sample reproducibility,
   forbidden-source, and report-idempotence tests against the exact candidate
   commit; report any underpowered result without promoting a threshold.
5. Update #351 only after #359's data and acceptance state are explicit.
