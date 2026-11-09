# Issue 351 progress checkpoint

This record tracks work in progress. It is not an acceptance or `VERIFIED`
record.

## Current state after #356 merge

- Issue: #351, first incomplete issue in the requested sequence; state OPEN.
- Branch: `codex/issue-351-valuation-evidence`.
- Current base sync: merge commit `a3fb9826` brings `origin/main` at
  `6ed0031f38b05740ae2fb47b7fbfe607963d92fa` into the existing branch without
  rewriting checkpoints `c109ae88e22937c134267c5dcd002b65074e90dc` and
  `df406030c485274146035bb2e7d5668b2badb977`.
- Pull request: #358 is OPEN as a draft and references #351 and blocker #359.
  Its current head is `4af4520a934c0945db9bd2856a891f683fe6d9fe`. GitHub run
  `42573746641` passed the required checks on that head. The draft does not
  claim to close #351.
- #356: closed by PR #357. The accepted report SHA-256 is
  `ce5f3f374071c63181dfa6fbd0b5a0501ebb6abd1ba3062ff7e73f0ba92fbc76`.
  It reports three primary issuer clusters, zero next-original-filing pairs,
  and zero primary fact labels. Its one-issuer Apple diagnostic has eight
  windows per model, seven first-subsequent filings, and zero complete labels.
  The descriptive Wilson 95% interval is `[0.0, 0.35433]`. No history
  threshold is supported; affected model results remain provisional or
  abstained.
- #339 and #350 remain open references; #350 retains the `blocker` label.
  Issues #352 through #355 are open and have not started. #352 depends on
  #351; #353 depends on #351 and #352; #354 depends on #352 and #353. #355 is
  optional and is not a core valuation dependency.
- #356 is CLOSED and remains in #351's `blockedBy` relation. New blocker #359
  is OPEN and linked as blocking #351. Its scope is representative,
  survivorship-aware SEC cohort evidence and model-specific chronological OOS
  thresholds. This is required because #351's numerical-threshold criterion
  is stricter than #356's accepted underpowered-report alternative.
- The root `.env` contains a contact-like SEC User-Agent value and is ignored
  by Git. `.env.example` now documents the required variable with a
  non-operational placeholder. The real contact value stays local and is not
  copied into the tracked example.
- #351 remains WIP and unverified. The three-of-five history rule is not a
  verified threshold, and the matrix does not claim otherwise. The single
  live SEC submissions request proves endpoint access only; it is not cohort
  or service-ingestion evidence.

## Current acceptance progress

| Criterion | Evidence | Status |
| --- | --- | --- |
| Inventory each required input for both released models. | Section 24.4.4 classifies SEC facts, derived metrics, forecasts, market inputs, policy inputs, capital bridge fields, and optional forward references. | Draft matrix present; final review pending. |
| Separate computability from evidence quality and define time, freshness, and quality gates. | The matrix keeps period and availability rules, immutable evidence references, versioned freshness policy, and typed degraded, provisional, unsupported, or abstained outcomes. | Draft matrix present; final review pending. |
| Define a numerical history threshold from representative coverage and chronological OOS evidence. | #356 report SHA-256 `ce5f3f374071c63181dfa6fbd0b5a0501ebb6abd1ba3062ff7e73f0ba92fbc76` reports no supported threshold. The matrix keeps three-of-five unvalidated and forbids it from granting `verified`. Blocker #359 records the missing cohort/OOS work. | NOT MET; #351 remains OPEN and #352 must not start. |
| Specify the multi-period data contract needed by #352. | The current producer requests point-in-time `revenue`, `operating_income`, `cash`, `debt`, and `diluted_shares`, plus transition filing evidence. The matrix names required annual duration and instant series with source and selection metadata. | Draft contract requirements documented. |
| Define fallback, editability, and required confirmation. | Source facts and derived history are read-only. Policy-marked assumptions may be overridden with preserved automatic evidence, `ManualProvenance`, a new digest, and caller-owned approval. | Draft policy documented; final review pending. |
| Keep guidance, analysts, Search, and LLM out of the default path. | The matrix assigns them to an optional reference path; #355 remains independent of the core sequence. | Draft policy documented; final review pending. |

## Verification on matrix checkpoint

The following checks ran on checkpoint `11c842b906b10693448d830e7018a6aa6b6f78d3`.
They do not yet cover later edits to this progress record.

| Command or request | Result |
| --- | --- |
| One SEC GET to `data.sec.gov/submissions/CIK0000320193.json` using the local `FUNDAMENTAL_SEC_USER_AGENT` | Exit 0. SEC returned CIK `0000320193`, Apple Inc., and 1,006 recent filing entries. The contact value was not logged. |
| `uv run --extra dev --project fundamental-service pytest fundamental-service/tests/test_sec_source.py fundamental-service/tests/test_source_acquisition.py fundamental-service/tests/test_history_sufficiency_report.py fundamental-service/tests/test_calibration.py fundamental-service/tests/test_facts.py fundamental-service/tests/test_verification.py -q` | Exit 0; 77 passed. |
| `python3 scripts/architecture_guard.py` | Exit 0; no boundary violations. |
| `docker compose --env-file .env.example config --quiet` | Exit 0. |
| `sha256sum docs/acceptance/issue-356-history-sufficiency-v1.json` | Exit 0; matched `ce5f3f374071c63181dfa6fbd0b5a0501ebb6abd1ba3062ff7e73f0ba92fbc76`. |
| `git diff origin/main...HEAD --check` | Exit 0. |

The live request proves the configured contact header can reach the SEC
submissions endpoint. It is one request, not a representative history cohort.
The #356 threshold result remains underpowered. No Docker service stack or
service-backed end-to-end request was run because this checkpoint changes
documentation and the environment example only.

## Current delivery gate

- #358 is a draft PR. Branch protection requires zero approving reviews; no
  review was requested or recorded. Required CI passed on
  `4af4520a934c0945db9bd2856a891f683fe6d9fe`, but that does not satisfy the
  unresolved numerical-threshold acceptance criterion.
- #359 is the linked `blocker` issue. #351 cannot be verified or merged and
  #352 cannot start until representative point-in-time cohort evidence
  supports the model-specific history decision.
- No Docker Compose project was started for this documentation-only slice.

## Verification on blocker checkpoint

Checkpoint `4af4520a934c0945db9bd2856a891f683fe6d9fe` records the WIP
acceptance state. These checks ran against that exact commit:

| Command or check | Result |
| --- | --- |
| `uv run --extra dev --project fundamental-service pytest fundamental-service/tests/test_sec_source.py fundamental-service/tests/test_source_acquisition.py fundamental-service/tests/test_history_sufficiency_report.py fundamental-service/tests/test_calibration.py fundamental-service/tests/test_facts.py fundamental-service/tests/test_verification.py -q` | Exit 0; 77 passed. |
| `python3 scripts/architecture_guard.py` | Exit 0; no boundary violations. |
| `docker compose --env-file .env.example config --quiet` | Exit 0. |
| `git diff origin/main...HEAD --check` | Exit 0. |
| GitHub Actions run `42573746641` on PR #358 | All 11 required checks passed. The documentation-only `fundamental-release-gate` was skipped. |

The SEC submissions GET is recorded above as a separate read-only smoke test.
It returned Apple filing metadata and did not expand the cohort. No Docker
service stack or service-backed end-to-end test ran.

## Previous checkpoint before #356 merged

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

## Acceptance progress at previous checkpoint

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

## Source and dependency findings at previous checkpoint

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

## Checks at previous checkpoint

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

## Next steps from the previous checkpoint

1. Resolve #356 in its owning evidence and cohort path, or record a justified
   underpowered outcome that keeps the affected baseline provisional or
   abstained.
2. Reconcile the threshold and source findings with #351's acceptance
   criteria, then review the complete source matrix.
3. Re-run checks against the exact candidate commit, open a PR that references
   #351, and keep both issues open until the required evidence and merge are
   complete.
