# Issue 359 progress checkpoint

This is a work-in-progress record, not acceptance or `VERIFIED` evidence.

## Current state

- Issue: #359, the blocker for #351's representative history-threshold evidence.
- State: OPEN; no threshold has been measured or approved.
- Branch: `codex/issue-359-sec-history-cohort`.
- Worktree: `/Users/denniswong/.codex/worktrees/value-investment-agent-issue-359-sec-history-cohort`.
- Base: `origin/main` at `6ed0031f38b05740ae2fb47b7fbfe607963d92fa`.
- Previous implementation checkpoint: `7c7be424`.
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

The full SEC response and archive-member hashes are recorded in
`frame_manifest.json`. Compressed offline snapshots preserve the SEC header
and every original 10-K index row, plus the 2016 Q1 10-K metadata columns used
for SIC and incorporation-country stratification. Both source-response hashes
and stored/unpacked artifact hashes are recorded; the manifest SHA-256 is
`a0c1bc6bfccbf91b75b8082ed416ed993a0beb919d9a3186cfcdf538a34c203d`.

## Verification on this checkpoint

| Check | Result |
| --- | --- |
| Parse `issue-359-cohort-protocol-v1.json` with Python's JSON parser | Exit 0; protocol schema and predeclared sample size validated. |
| Reconcile SEC source hashes and master-index/data-set frame counts | Exit 0; 5,462 original 10-K rows, 5,338 index CIKs, 4,494 matched data-set CIKs, 3,999 US-incorporated CIKs, 844 unmatched exclusions, and 495 non-US/unknown exclusions matched the protocol. |
| Verify retained gzip snapshots by stored and uncompressed hashes | Exit 0; both snapshots match `frame_manifest.json`, with 5,462 index 10-K rows and 4,498 data-set 10-K rows. |
| `git diff --check` | Exit 0. |
| `uv run --extra dev --project fundamental-service pytest fundamental-service/tests/test_history_cohort.py -q` before report-scope fix | Exit 1; 3 passed and 1 failed because report assembly referenced undefined `protocol`. |
| `uv run --extra dev --project fundamental-service pytest fundamental-service/tests/test_history_cohort.py -q` after report-scope fix | Exit 1; 3 passed and 1 failed because the test frame fixture lacks `eligible` and `excluded` lists. |
| `uv run --extra dev --project fundamental-service pytest fundamental-service/tests/test_history_cohort.py -q` after fixture correction | Exit 0; 4 passed. |
| `uv run --extra dev --project fundamental-service pytest fundamental-service/tests/test_history_cohort.py -q` during typed frame cleanup | Exit 1; 3 passed and 1 failed because the refactor dropped the original master-index filing count. |
| `uv run --extra dev --project fundamental-service pytest fundamental-service/tests/test_history_cohort.py -q` after restoring the filing count | Exit 0; 4 passed and the deterministic sample digest remained unchanged. |
| `python3 scripts/architecture_guard.py` | Exit 0; no boundary violations. |
| `pre-commit run ruff --files fundamental-service/src/fundamental_service/history_cohort.py fundamental-service/tests/test_history_cohort.py` | Exit 127; standalone `pre-commit` command is not on `PATH`. Git commit hooks ran Ruff and Ruff format successfully on checkpoint `ce604587`. |
| `uv run --extra dev --project fundamental-service ruff check fundamental-service/src/fundamental_service/history_cohort.py fundamental-service/tests/test_history_cohort.py` | Exit 2; Ruff is not installed in the Fundamental Service environment. The repository pre-commit Ruff hook is available. |
| `uv run --extra dev --project fundamental-service ruff format --check fundamental-service/src/fundamental_service/history_cohort.py fundamental-service/tests/test_history_cohort.py` | Exit 2; Ruff is not installed in the Fundamental Service environment. The repository pre-commit Ruff hook is available. |
| Repository large-file pre-commit gate | Initial full-source gzip files exceeded the 500 KB per-file limit. The retained, hash-verified SEC row subsets are 129,471 and 120,531 bytes. |
| Company Facts and submissions cohort capture | Not run |
| Model-field coverage and first-subsequent labels | Not run |

No Docker Compose project is needed for this data-acquisition and report slice.

## Next steps

1. Fix report assembly to read the scope from the verified frame protocol, then
   rerun the cohort tests.
2. Inspect capture and report artifact sizes before starting the live cohort.
3. Capture the selected cohort using the local User-Agent without exposing its
   value; retain retrieval failures in the denominator.
4. Run temporal-ordering, original-versus-amendment, sample reproducibility,
   forbidden-source, and report-idempotence tests against the exact candidate
   commit; report any underpowered result without promoting a threshold.
5. Update #351 only after #359's data and acceptance state are explicit.

## Latest implementation status

The deterministic sample selector returns 100 unique CIK clusters across the
declared filing-time SIC strata. The report reads its sampling scope from the
verified frame protocol, and the capture-resume fixture now includes the
population lists returned by `load_frame()`. The focused suite passes all four
tests. The frame loader now returns typed frame and sample records and parses
the pinned CSV fields at its boundary. It retains the original filing count,
the predeclared sample digest, and all exclusion counts. The report module no
longer uses `Any`. No live issuer Company Facts capture was run. Checkpoint
`7c7be424` preserves the fixture correction. The typed boundary cleanup builds
on that checkpoint and passes the listed focused checks. This is not acceptance
evidence. The next step is to finish typed parsing for capture/report artifacts
and verify one issuer's live snapshot size before starting cohort capture.
