# Issue 351 progress checkpoint

This record tracks work in progress. It is not an acceptance or `VERIFIED`
record.

## Current state

- Issue: #351, "Define evidence and policy sources for every valuation input"
- Blocker: #356 requires representative point-in-time cohorts and chronological
  out-of-sample evidence for the annual-history threshold.
- GitHub dependency: #351 is formally blocked by #356.
- Branch: `codex/issue-351-valuation-evidence`
- Source matrix checkpoint: `c109ae88e22937c134267c5dcd002b65074e90dc`
- Pull request: none
- Merge and issue closure: pending

At this checkpoint, #351 is the first incomplete issue in the requested
sequence. Issues #339 and #350 remain open dependencies. Issues #352 through
#355 remain open and have not started. No pull request is open for this branch.
The local branch is one commit ahead of `origin/main`. GitHub has no check-run
record for the unpushed source matrix commit.

## Acceptance progress

| Criterion | Evidence at this checkpoint | Status |
| --- | --- | --- |
| Cover every required input for `fcff_dcf` and `transition_fcff_dcf` with source class, owner, policy or formula, evidence, time rule, freshness, quality, fallback, editability, and abstention behavior. | The source matrix in section 24.4.4 of `fundamental-enterprise-grade-target-state.md` covers these inputs. | Draft documented; review pending. |
| Separate mathematical computability from evidence quality and distinguish observed facts from assumptions and model-derived values. | The matrix labels SEC-observed, market-observed, computed, policy-resolved, and model-derived values, with quality outcomes. | Draft documented; review pending. |
| Identify missing canonical history inputs and define the multi-period contract required by #352. | The current producer requests only `revenue`, `operating_income`, `cash`, `debt`, and `diluted_shares`, with `filed_operating_evidence` added for the transition model. The matrix specifies annual duration series, instant series, fact metadata, and selected/rejected candidate reasons for #352. | Source gap confirmed; contract documented. |
| Define provisional, degraded, or abstained outcomes for insufficient, stale, conflicting, broken, or unlicensed evidence. | The matrix rejects placeholders and defines provisional or abstained outcomes for unresolved inputs. It records that a source registry entry or terms URL does not establish permitted use. | Draft documented; threshold evidence pending. |
| Do not abstain solely because company guidance or analyst estimates are absent. | The matrix marks company guidance and analyst forecasts as optional references that cannot overwrite the baseline. | Draft documented; review pending. |
| Keep Search, LLM, and external forecasts out of the default path. | The matrix defers them to #355 as opt-in references and prohibits them from replacing the baseline. | Draft documented; review pending. |
| Preserve automatic values and evidence when a user makes a manual edit, with author, time, and reason. | The matrix requires `ManualProvenance` and preservation of the automatic value and evidence. | Draft documented; review pending. |

The three-of-five annual-history rule remains a candidate. It cannot grant
`verified` eligibility until #356 reports representative coverage and
chronological point-in-time OOS evidence for each model. The service's
21-case engineering cohort uses Apple and Tesla filing fixtures and remains
replay evidence, not a calibration or sufficiency cohort. The legacy
20-case backtest reports consensus-gap metrics and has no chronological split
manifest for the released Fundamental service models.

## Source and dependency findings

- SEC acquisition and filing snapshots exist in Fundamental Service. The
  Agent Core request producer still resolves a narrow point-in-time field set;
  it does not request the annual history needed to derive growth and
  reinvestment.
- Treasury capture exists, but the normal valuation path has not been shown to
  resolve it into WACC. FRED/ALFRED and Damodaran are registered for capture,
  but their use in the FCFF path and intended-use terms review are unproven.
- The Fundamental source catalog has no evidenced lawful free point-in-time
  share-price provider. Cost of debt and normalized tax still require a cited
  reviewer assumption package or abstention.
- #339 and #350 remain open. #350 retains the `blocker` label. #356 is open
  with the `blocker` label and blocks #351 acceptance and #352. GitHub now
  records #356 as #351's `blocked by` dependency.
- No open PR or CI run covers the local branch. The source matrix commit has
  not been pushed, so GitHub returns no check runs for that SHA.

## Checks

Commands and results below were run while examining the source matrix at
`c109ae88e22937c134267c5dcd002b65074e90dc`:

| Command | Result |
| --- | --- |
| `git status --short --branch` | Exit 0. Worktree clean; branch is one commit ahead of `origin/main`. |
| `git diff origin/main...HEAD --check` | Exit 0. No whitespace errors in the source matrix diff. |
| `uv run pytest tests/test_verification.py -q` from `fundamental-service/` | Exit 2. The default environment did not include the optional `pytest` dependency. |
| `uv run --extra dev pytest tests/test_verification.py -q` from `fundamental-service/` | Exit 0. Seven tests passed, including the fixture-bound engineering cohort checks. |
| `gh pr list --state open --limit 100` | Exit 0. No open pull requests. |
| `gh issue edit 351 --add-blocked-by 356` | Exit 0. GitHub now reports #356 in #351's `blockedBy` list. |
| `gh api repos/sosodennis/value-investment-agent/commits/c109ae88e22937c134267c5dcd002b65074e90dc/check-runs` | Exit 1. GitHub returned HTTP 422 because this local commit is not present on GitHub. No CI result exists for it. |

No Docker project or service-backed acceptance was run. This checkpoint changes
documentation only and does not change a service or user workflow. No live SEC
query was run; this environment has no configured `FUNDAMENTAL_SEC_USER_AGENT`.

## Next steps

1. Resolve #356 in its owning evidence and cohort path, or record a justified
   underpowered outcome that keeps the affected baseline provisional or
   abstained.
2. Reconcile the threshold and source findings with #351's acceptance
   criteria, then review the complete source matrix.
3. Re-run checks against the exact candidate commit, open a PR that references
   #351, and keep both issues open until the required evidence and merge are
   complete.
