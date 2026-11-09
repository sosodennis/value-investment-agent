# Issue 356 progress checkpoint

This record tracks work in progress. It is not an acceptance or `VERIFIED`
record.

## Current state

- Issue: #356, "Validate annual-history sufficiency with chronological OOS evidence"
- Blocks: #351 acceptance and #352 start
- Branch: `codex/issue-356-history-sufficiency`
- Base commit: `f613db164a2251637aaf14d2abbf9e1866c39df9`
- Pull request: none
- Merge and issue closure: pending

The only available production-source fixtures cover Apple and Tesla. They do
not form a representative issuer cohort, and the existing 21-case verification
cohort repeats those two issuers across cases and sector labels. The 20-case
legacy backtest uses a consensus-gap target and synthetic/manual DCF inputs;
it is not valid history-sufficiency or intrinsic-value evidence.

No broader SEC cohort has been collected. `FUNDAMENTAL_SEC_USER_AGENT` is not
configured in this worktree. No SEC network request or Docker stack was started.
An approved public contact string is needed before this work can collect a
larger point-in-time cohort from SEC endpoints.

## Available source evidence

| Source | Stable reference | What it supports | Limitation |
| --- | --- | --- | --- |
| Apple Company Facts | Snapshot `apple-companyfacts.json`, SHA-256 `75a78f918313f3336823517d6c34908d23dd07f07e90e625c61e705e3bb6d27b`, captured 2026-11-03 | Accession-level annual facts with `filed`, form, period, and value fields; historical selection can be reconstructed by filtering on filing availability. | One issuer. The Company Facts capture itself postdates the historical decisions and is not a substitute for pinned filing snapshots. |
| Apple FY2024 10-K | Accession `0000320193-24-000123`, filed 2024-11-01 10:01:36 UTC, SHA-256 `a14d584e9804a87e92ddbd2446ade975e926a494671292403c811c1f4fc4b846` | Original filing bytes and filing timestamp for one mature-issuer snapshot. | One issuer-period. |
| Tesla FY2023 10-K | Accession `0001628280-24-002390`, filed 2024-01-29 01:34:42 UTC, SHA-256 `450428c73c70775ccc288b2ac48ac2d6b81a128357fe6e92f0cf3ab76a05322e` | Original filing bytes and filing timestamp for one high-growth/automotive issuer snapshot. | No corresponding subsequent original annual filing is present for a realized next-period label. |
| Tesla 10-K/A | Accession `0001104659-25-042659`, filed 2025-04-30 21:08:56 UTC, SHA-256 `ac21201742aa3e815678e0f1dad7605b9f659423966981497b1e1e285233a432` | Amendment bytes and an amendment relation to accession `0001628280-25-003063`. | Amendment scope is `unknown`; the original referenced filing is absent, so this amendment cannot stand in as the first subsequent label. |
| Microsoft FY2024 parser package | Test fixture `microsoft-2024-original-xbrl-test-package.zip`, SHA-256 `9315745e8b66735afd8be0f63a2d5876d350eb7ae7be80a7e0aff015df76acf0`. The official [SEC filing index for accession 0000950170-24-087843](https://www.sec.gov/Archives/edgar/data/789019/000095017024087843/0000950170-24-087843-index.htm) records a 2024-07-30 acceptance time of 16:06:22 UTC. | The SEC index confirms Microsoft CIK `0000789019`, a 2024-06-30 report period, and SIC 7372. | The fixture is listed under `test_fixtures`, not captured sources. Its filing member is 6,860,910 bytes; the SEC index lists 6,860,911 bytes. The byte mismatch means the fixture cannot prove an exact immutable SEC snapshot. Excluded from cohort counts. |

The existing engineering fixture has 21 cases: 10 positive, 9 abstention, and
2 degraded. They reference three snapshot IDs, but those IDs resolve to only
the Apple and Tesla filing fixtures. Sector labels in the engineering cases do
not create additional issuer observations.

## Acceptance progress

| Criterion | Evidence at this checkpoint | Status |
| --- | --- | --- |
| Define a representative U.S. GAAP cohort with issuer identity history and exclusions. | Available source inventory contains two issuers and no historical filing-frame selection. | Not met. |
| Build chronological point-in-time snapshots and first-subsequent-filing labels. | Existing service contracts and unit tests cover point-in-time facts, first subsequent publication, and restatement diagnostics. No issue-specific cohort manifest or issuer-period rows exist. | Existing primitives verified; cohort not built. |
| Report model- and field-level coverage plus chronological OOS results and uncertainty intervals. | No issue-specific field-coverage report, OOS metrics, or precision report exists. | Not met. |
| Decide whether the three-of-five rule is supported or evidence is underpowered. | The available data cannot establish representative coverage or an issuer-clustered precision interval. | Candidate rule remains unvalidated; affected results must remain provisional or abstain. |
| Test temporal ordering, first subsequent labels, amendments, reproducibility, and exclusion of analyst/consensus/Search/LLM data. | Existing tests cover temporal ordering, first publication, and amendment behavior. Issue-specific cohort reproducibility and forbidden-source tests have not been added. | Partially covered by existing tests only. |
| Record exact-commit checks and artifact hashes in the linked #351 acceptance record. | #351 has a WIP record at `docs/acceptance/issue-351-progress-2026-11-09.md`; this #356 checkpoint is not yet linked there. | Pending. |

## Baseline checks

These commands ran against base commit
`f613db164a2251637aaf14d2abbf9e1866c39df9`:

| Command | Result |
| --- | --- |
| `uv run --extra dev --project fundamental-service pytest fundamental-service/tests/test_calibration.py -q` | Exit 0; 20 passed. |
| `uv run --extra dev --project fundamental-service pytest fundamental-service/tests/test_facts.py -q` | Exit 0; 13 passed. |
| `git diff origin/main...HEAD --check` | Exit 0; no changes at the clean base. |

These baseline tests establish behavior in existing primitives only. They do
not establish the requested cohort or OOS evidence.

## Next steps

1. Use an approved identifiable SEC User-Agent and a historical filing frame
   that does not start from today's ticker list, then capture immutable source
   bytes and their hashes.
2. Build the issuer-period manifest from point-in-time SEC facts. Keep missing,
   amended, structurally broken, and out-of-profile rows with exclusion reasons.
3. Evaluate the three-of-five rule by model and industry on chronological
   outcomes. Report issuer-level uncertainty and retain provisional or
   abstained status if the predeclared precision target is not met.
4. Add reproducibility and temporal-leakage tests, run them against the exact
   candidate commit, and link the result from #351 before resolving this
   blocker.
