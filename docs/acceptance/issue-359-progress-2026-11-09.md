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
population lists returned by `load_frame()`. The frame loader returns typed
frame and sample records and parses the pinned CSV fields at its boundary. It
retains the original filing count, the predeclared sample digest, and all
exclusion counts. The report module no longer uses `Any`. Checkpoint `7c7be424`
preserves the fixture correction. The typed boundary cleanup passes the listed
focused checks. The first live cohort capture is recorded below; it is not
acceptance evidence.

## Live cohort capture WIP

Capture ran from exact code commit `9b4abf9f73229f8eea3a29fc72df4c7c2911b400`
on 2026-11-09 with the main checkout's ignored `.env`. The environment example
already contains a quoted, non-operational `FUNDAMENTAL_SEC_USER_AGENT`
placeholder. The local contact value was not copied, printed, or staged.

Command:

```sh
uv run --env-file /Users/denniswong/Desktop/Project/value-investment-agent/.env --project fundamental-service python -m fundamental_service.history_cohort capture
```

The command exited 2 and reported `partial`. The preselected sample retained
all 100 issuer clusters. It wrote 68 valid snapshots, marked 32 as
`INVALID_SOURCE_SNAPSHOT`, and marked none pending or as transport failures.
The capture manifest SHA-256 is
`4497c7842177347d60ef08fab732d81af05d44733fe681ef7606c112aba6fa59`. All
captured snapshot files are below the repository's 500 KB per-file limit.

The focused test command on the same code commit passed 45 tests:

```sh
uv run --extra dev --project fundamental-service pytest fundamental-service/tests/test_history_cohort.py fundamental-service/tests/test_history_sufficiency_report.py fundamental-service/tests/test_calibration.py fundamental-service/tests/test_facts.py -q
```

A read-only retry of the first invalid CIK reproduced `ReportError: SEC CIK
must be numeric and at most ten digits`. The SEC historical submissions
response had no top-level `cik`; its SEC-provided archive filename included the
selected CIK. The current capture code validates every historical payload only
through its top-level `cik`, so it rejects these otherwise parseable archives.
The diagnostic request did not write or replace a snapshot.

The capture boundary now validates each historical archive's SEC-provided
filename against the selected CIK. If the payload includes a top-level `cik`,
the boundary also verifies that value. The targeted regression command passed
four cases: matching and mismatched filenames, each with the payload `cik`
absent or present.

Status: WIP, not acceptance. The identity fix passed its tests, but the live
capture exposed a second SEC archive shape difference recorded below.

## SEC archive row-shape follow-up

The capture retry on exact code commit `10b69b013f12182b171544b93e6510b173e91e6f`
again exited 2 with 68 of 100 issuer snapshots captured and 32 marked
`INVALID_SOURCE_SNAPSHOT`. No issuer was replaced; the manifest SHA-256
remained `4497c7842177347d60ef08fab732d81af05d44733fe681ef7606c112aba6fa59`.

A read-only SEC request for CIK `0001361538` returned archive
`CIK0001361538-submissions-001.json`. The archive has 326 entries in each of
the top-level `form`, `accessionNumber`, `filingDate`, `reportDate`, and
`acceptanceDateTime` arrays. It has neither a top-level `cik` nor a nested
`filings` object. The current filing parser expects `filings.recent`, so the
archive fails with `submissions.filings must be an object` after identity
validation succeeds.

The regression fixture uses the observed flat array shape and checks that its
historical accession is retained in the stored snapshot. The capture boundary
maps those five SEC columns into the existing `filings.recent` shape for
measurement. It keeps the response hash and metadata from the original SEC
bytes. The targeted regression command passed all four cases. Next, run the
full focused suite on the fix commit, resume the same fixed sample, and report
the measured threshold status without replacing issuers or promoting an
unsupported threshold.

## Latest complete cohort and report

The completed capture ran with code commit
`a9ede6398fdb694a9e03746e57f711e8e401e17c` and the main checkout's ignored
`.env`. The command exited 0 with status `complete`: 100 selected and captured
issuer clusters, with no transport failures or invalid snapshots. It reused the
68 verified snapshots and added snapshots for the remaining selected issuers.
The final capture manifest SHA-256 is
`afad3f92f2597383d16afec2cc85850fbf5919106d3cb827a6e8112022836242`.

The report command exited 0 on two runs. The first run wrote the report; the
second returned `wrote: false` with the same SHA-256,
`ee29c9cff88757b4be7e9eb58747dc5eba86e6a072d25f081f3cfd2e4337c3b3`.
The 6,951,874-byte JSON is stored as `report.json.gz` at 331,027 bytes. Its
SHA-256 is `57bfdf339c0f3cf5deeb58492a592f720e643569c0d0d3cafcfc68e8045ed88b`.
`gzip -dc report.json.gz | shasum -a 256` reproduces the uncompressed JSON
SHA-256 above.

Both models retain all 100 issuer clusters in their denominator. Each model
has 78 five-period measurement windows. The candidate rule, three complete
periods in the latest five, has 0 eligible issuers out of 100. A first
subsequent original 10-K is available for 91 issuers, but complete first-
subsequent labels are 0 out of 100, or 0 out of 91 when conditioned on a next
filing. Revenue and contract-liability coverage each reaches three periods for
0 out of 100 issuers. Historical forecast accuracy was not measured because no
Fundamental Service forecasts exist for these decision dates.

The report records threshold status
`history_evidence_measured_threshold_review_required` and
`supported_history_threshold: null`. The 100-cluster sample-size criterion is
met, but the observed field coverage and out-of-sample labels do not support a
history eligibility threshold. Keep affected results provisional or abstained.
Do not treat the candidate three-of-five rule as validated. The report excludes
current ticker/survival data, analyst estimates, Search, and LLM-extracted
values.

On code commit `a9ede6398fdb694a9e03746e57f711e8e401e17c`, the focused
Fundamental Service suite passed 49 tests, `python3
scripts/architecture_guard.py` passed, and `git diff origin/main...HEAD --check`
passed. Commit hooks passed Ruff, Ruff format, whitespace, and the 500 KB
large-file check. No Docker or service-backed acceptance ran; this issue
validates SEC snapshot capture and the offline report. The `.env.example`
contains a quoted placeholder, and the local contact remains only in the
ignored `.env`.

Status: WIP, not VERIFIED. The measured evidence supports no threshold, so #359
remains open and #351 remains blocked until the source mapping and abstention
policy can use this result. Do not start #352.
