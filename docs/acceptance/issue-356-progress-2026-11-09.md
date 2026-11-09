# Issue 356 progress checkpoint

This is a work-in-progress record, not acceptance or `VERIFIED` evidence.

## Current state

- Issue: #356, "Validate annual-history sufficiency with chronological OOS evidence"
- Blocks: #351 acceptance and #352 start
- Branch: `codex/issue-356-history-sufficiency`
- Base commit: `f613db164a2251637aaf14d2abbf9e1866c39df9`
- Prior checkpoint before this report: `e82d029bf7beaca7035ffa50f2bd19911ee75991`
- Pull request: none
- Merge and issue closure: pending

The latest evidence artifact is generated from checked-in SEC fixtures. The
worktree does not have an approved `FUNDAMENTAL_SEC_USER_AGENT`; the repository
Compose default is a placeholder, so no SEC network request was made. An
approved User-Agent was requested on 2026-11-09. Do not treat the current
three-issuer fixture inventory as representative or close #356 on this record.

## Available source evidence

The primary fixture inventory has three issuer clusters and no subsequent
original annual filing snapshots for OOS fact labels:

| Issuer | Filing snapshot | Availability | Classification / limitation |
| --- | --- | --- | --- |
| Apple (`CIK:0000320193`) | FY2024 10-K, accession `0000320193-24-000123` | 2024-11-01 10:01:36 UTC | Original filing bytes are hash-verified. No pinned SIC or historical identity crosswalk is available in the filing snapshot. |
| Tesla (`CIK:0001318605`) | FY2023 10-K, accession `0001628280-24-002390` | 2024-01-29 01:34:42 UTC | Original filing bytes are hash-verified. No pinned SIC or historical identity crosswalk is available in the filing snapshot. |
| Microsoft (`CIK:0000789019`) | FY2024 10-K, accession `0000950170-24-087843` | 2024-07-30 16:06:22 UTC | Both canonical SEC archive member hashes match the local XBRL fixture. The HTML member is one byte smaller than the SEC index metadata; this remains a metadata warning, not a member-integrity failure. SEC SIC 7372 is available. |

The Tesla 10-K/A accession `0001104659-25-042659` is excluded because its
amendment scope is unknown and the referenced original filing is absent. The
engineering verification fixtures and legacy consensus-relative backtest do
not add independent issuer observations.

The Apple Company Facts capture is a post-capture aggregate, dated
2026-11-03. It is used only as a one-issuer diagnostic: the report filters
original 10-K facts by accession, fiscal period, unit, and filing acceptance
time, and does not use later amendment values as historical inputs. It is not a
substitute for a representative cohort of immutable filing snapshots.

## Report result

Command:

```sh
uv run --extra dev --project fundamental-service python -m fundamental_service.history_sufficiency_report
```

Evidence artifact: `docs/acceptance/issue-356-history-sufficiency-v1.json`

- Capture manifest SHA-256: `d7ca79f45f231ce118e7433a9773a24072eeae50b91fdd57c90461f1e903f5fc`
- Report SHA-256: `232b310209fd7f2c18602e3a26c3183674a424c4231206d5991cdc04fe10a95f`
- Primary cohort: 3 issuer clusters; 1 issuer has a filing-pinned SIC; 0 next-original-snapshot pairs; 0 primary-cohort fact labels.
- Diagnostic pilot: 1 issuer, 8 five-period windows for each released model family; 0 windows pass the candidate rule of at least 3 complete periods in the latest 5 original annual filing periods.
- The report keeps 398 unique source facts in one catalog; all historical-window fact IDs resolve to it.
- OOS completeness: 0 eligible labels and no estimable interval; no historical Fundamental service forecasts exist, so forecast accuracy is not measured.
- Threshold decision: `underpowered`; no threshold is supported; affected results remain provisional or abstained.
- Two consecutive report runs returned the same SHA-256; the second reported `wrote: false`.

The report names unmeasured negative or near-zero denominators, loss-making
periods, volatility/cyclicality, structural breaks, conflicting mappings,
reviewed normalized-tax policy, operating-working-capital comparability, and
transition-model operating evidence. Search, LLM, analyst target, and consensus
sources are not read.

## Acceptance progress

| Criterion | Evidence | Status |
| --- | --- | --- |
| Representative U.S. GAAP issuer cohort with identity history, industry coverage, and exclusions. | Three selectively checked-in issuer snapshots; only Microsoft has filing-pinned SIC; no historical identity/successor crosswalk or representative sampling frame. Tesla amendment exclusion is explicit. | Not met; requires broader approved source capture. |
| Point-in-time snapshots and first subsequent eligible filing labels. | Stable CIK/accession rows carry period, availability, valuation timestamp, source hash, inclusion/exclusion reason, and next-original snapshot status. The primary fixtures contain no subsequent original filing snapshot. Apple diagnostic selects original facts only when available by the valuation timestamp. | Partially met; no primary fact labels. |
| Model- and field-level coverage plus chronological OOS results and uncertainty. | Both model families report field coverage across eight Apple diagnostic windows, per-period source fact references, first-subsequent filing selection, and label completeness. Neither model has a passing candidate window or eligible label; the period-level Wilson interval is therefore null, and issuer-cluster intervals are not estimable. | Partial diagnostic only; underpowered. |
| Decide the candidate history threshold without overstating evidence. | The 3-of-5 complete-period candidate is unvalidated; both model families and the shared decision mark results provisional or abstained. | Met for explicit underpowered status only; threshold not established. |
| Test time ordering, labels, amendment handling, reproducibility, and forbidden sources. | New tests cover point-in-time selection, first-subsequent original filing, amendment exclusion, walk-forward windows, missing-period detection, report idempotence, and source exclusions. | Local tests pass; broader representative evidence remains unavailable. |
| Record exact commit and verification evidence in the linked #351 acceptance record. | This checkpoint and report are prepared; the exact post-commit SHA and rerun commands must still be recorded in the #351 issue acceptance comment. | Pending. |

## Verification

These checks passed on the current candidate tree before its next checkpoint
commit:

| Command | Result |
| --- | --- |
| `uv run --extra dev --project fundamental-service pytest fundamental-service/tests/test_history_sufficiency_report.py fundamental-service/tests/test_calibration.py fundamental-service/tests/test_facts.py -q` | Exit 0; 40 passed. |
| `uvx --from ruff ruff check fundamental-service/src/fundamental_service/history_sufficiency_report.py fundamental-service/tests/test_history_sufficiency_report.py` | Exit 0; all checks passed. |
| `python3 -m compileall -q fundamental-service/src/fundamental_service/history_sufficiency_report.py fundamental-service/tests/test_history_sufficiency_report.py` | Exit 0. |
| `python3 scripts/architecture_guard.py` | Exit 0; no boundary violations. |
| `git diff --check` | Exit 0. |
| Report command, run twice | Both exit 0; same SHA-256; second run did not rewrite the file. |

No Docker stack, service-backed end-to-end test, SEC network request, GitHub CI,
PR, or review has run. The report is an offline diagnostic and does not change
runtime service behavior; #356 remains open and blocks #351 acceptance.

## Next steps

1. Use an approved identifiable SEC User-Agent to add immutable, historical filing snapshots and a predeclared issuer sampling frame.
2. Extend point-in-time fact panels and labels by issuer and model, then evaluate industry coverage and issuer-cluster uncertainty; retain the underpowered outcome if the sample gate still fails.
3. Re-run checks on the exact checkpoint/PR commit, record its SHA and artifact hash on #356 and the linked #351 acceptance record, then complete required review, CI, merge, and issue closure before starting #351.
