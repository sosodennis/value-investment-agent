# Issue 356 progress checkpoint

This is a work-in-progress record, not acceptance or `VERIFIED` evidence.

## Current state

- Issue: #356, "Validate annual-history sufficiency with chronological OOS evidence"
- Blocks: #351 acceptance and #352 start
- Branch: `codex/issue-356-history-sufficiency`
- Base commit: `f613db164a2251637aaf14d2abbf9e1866c39df9`
- Prior checkpoint before this status update: `71e088607b9e46f8ae59eed97e96289a145e3091`
- Pull request: [#357](https://github.com/sosodennis/value-investment-agent/pull/357), targeting `main`
- Merge and issue closure: pending

The latest evidence artifact is generated from checked-in SEC fixtures. The
process environment and project `.env` files do not set an approved
`FUNDAMENTAL_SEC_USER_AGENT`. The repository contains a test-only User-Agent
and a Compose placeholder. Neither is treated as approved, and no SEC network
request was made. The user chose existing snapshots only on 2026-11-09. Do not
treat the current three-issuer fixture inventory as representative.

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
- Report SHA-256: `ce5f3f374071c63181dfa6fbd0b5a0501ebb6abd1ba3062ff7e73f0ba92fbc76`
- Primary cohort: 3 issuer clusters; 1 issuer has a filing-pinned SIC; 0 next-original-snapshot pairs; 0 primary-cohort fact labels.
- Diagnostic pilot: 1 issuer, 8 five-period windows for each released model family; 0 windows pass the candidate rule of at least 3 complete periods in the latest 5 original annual filing periods.
- The report keeps 398 unique source facts in one catalog; all historical-window fact IDs resolve to it.
- OOS completeness: 7 of 8 diagnostic decisions have a first subsequent original filing, but none has a complete measured label set. The period-level Wilson 95% interval is `[0.0, 0.35433]` and is descriptive only because the periods belong to one issuer. The candidate-gate subset has 0 eligible decisions and no estimable interval. No historical Fundamental service forecasts exist, so forecast accuracy is not measured.
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
| Cohort and included/excluded issuer-periods have stable source and time identifiers. | The three checked-in original filing snapshots and the excluded Tesla amendment have stable CIK, accession, period, availability, valuation timestamp, source hash, and inclusion or exclusion reason. Only Microsoft has a filing-pinned SIC, and no historical identity crosswalk or representative sampling frame exists. | Met for the available fixture inventory; evidence is underpowered for a representative threshold. |
| Point-in-time ordering and first-subsequent labels exclude current ticker lists and later restatements. | The report uses CIK/accession identity, selects original Apple facts by period and filing acceptance time, and records first-subsequent filing labels. Tests cover later-publication exclusion and first-original-filing selection. The primary fixture cohort has no subsequent original snapshot pairs. | Met for the captured inputs; the primary cohort has no fact labels. |
| Both model families have field coverage and chronological OOS results with uncertainty intervals and a justified sample-size policy. | Both models report eight Apple diagnostic windows, seven decisions with a first subsequent filing, zero complete measured label sets, and a descriptive period-level Wilson interval of `[0.0, 0.35433]`. The 100-independent-issuer policy keeps this one-issuer result underpowered; issuer-cluster intervals are not estimable. | Reported; underpowered, with no supported threshold. |
| Decide the candidate history threshold without overstating evidence. | The 3-of-5 complete-period candidate is unvalidated; both model families and the shared decision mark results provisional or abstained. | Met for explicit underpowered status only; threshold not established. |
| Test time ordering, labels, amendment handling, reproducibility, and forbidden sources. | Tests cover point-in-time selection, first-subsequent original filing, amendment exclusion, walk-forward windows, candidate-gate-independent label completeness, missing-period detection, report idempotence, and source exclusions. | Met locally; representative evidence remains unavailable. |
| Record exact commit and verification evidence in the linked #351 acceptance record. | Commit `71e088607b9e46f8ae59eed97e96289a145e3091`, report hash, capture-manifest hash, and local commands are recorded in the #351 issue comment. PR #357 checks passed on this implementation commit. | Recorded; the status-document commit still needs its own checks. |

## Verification

These checks passed on implementation commit
`71e088607b9e46f8ae59eed97e96289a145e3091` before this status-document
checkpoint:

| Command | Result |
| --- | --- |
| `uv run --extra dev --project fundamental-service pytest fundamental-service/tests/test_history_sufficiency_report.py fundamental-service/tests/test_calibration.py fundamental-service/tests/test_facts.py -q` | Exit 0; 41 passed. |
| `uvx --from ruff ruff check fundamental-service/src/fundamental_service/history_sufficiency_report.py fundamental-service/tests/test_history_sufficiency_report.py` | Exit 0; all checks passed. |
| `python3 -m compileall -q fundamental-service/src/fundamental_service/history_sufficiency_report.py fundamental-service/tests/test_history_sufficiency_report.py` | Exit 0. |
| `python3 scripts/architecture_guard.py` | Exit 0; no boundary violations. |
| `git diff --check` | Exit 0. |
| `uv run --extra dev --project fundamental-service python -m fundamental_service.history_sufficiency_report`, run twice | Both exit 0; SHA-256 `ce5f3f374071c63181dfa6fbd0b5a0501ebb6abd1ba3062ff7e73f0ba92fbc76`; the second run reported `wrote: false`. |
| GitHub required checks on PR #357, run `42569286271` | All eight required checks passed on the implementation commit; branch protection requires zero approving reviews. |

No Docker stack or service-backed end-to-end test was run because this change
only builds an offline evidence report and does not change runtime behavior. No
SEC network request was made. PR #357 is open. Its eight required checks passed
on implementation commit `71e088607b9e46f8ae59eed97e96289a145e3091`; this
status-document checkpoint must pass checks before merge. No approving review
is required. Both valuation paths remain provisional or abstained.

## Next steps

1. Commit this #356 status update and rerun local checks on its exact SHA.
2. Wait for all required checks on the updated PR head, then merge PR #357 and confirm #356 closes.
3. Record the final head and merge evidence on #356 and #351, then start #351 in its own issue worktree.
