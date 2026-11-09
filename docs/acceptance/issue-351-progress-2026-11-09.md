# Issue 351 progress checkpoint

This record tracks work in progress. It is not an acceptance or `VERIFIED`
record.

## Current status (2026-11-09)

- #351 remains the first incomplete issue in the fixed sequence. It is OPEN on
  `codex/issue-351-valuation-evidence`; PR #358 is OPEN as a draft. The PR
  still advertises the older head `68f305abaae1038eeeaa7b434cd45e1adadf9672`
  until this policy checkpoint is pushed.
- The user confirmed that #351 should deliver the source and quality matrix
  with a safe provisional or abstention policy. The three-of-five history
  rule remains an unvalidated candidate and cannot grant `verified` status.
  Do not replace it with a five-year rule based on intuition.
- The merged #359 cohort report remains underpowered. It has 100 selected
  issuer clusters, 0/100 eligible cases and 0/100 complete first-subsequent
  labels under its listed mapping. It records no historical Fundamental
  Service forecasts and keeps `supported_history_threshold` null.
- The separate #361 worktree has local checkpoint
  `157604cad183c6c5609252c5502fd059569afc99`. Its candidate-tag report finds
  56/100 clusters with a listed tag in three of five periods. That is an
  unreviewed tag screen, not canonical coverage or a threshold. The same
  allowlist now filters live captures and saved evidence.
- Checks on #361 commit `157604cad183c6c5609252c5502fd059569afc99` passed:
  54 focused tests, `python3 scripts/architecture_guard.py`, report
  regeneration with SHA-256
  `508e721bfaa564eeb08a2f17a37e33405a346b78a11f7b870f4c4f9d855bb0ed`, and
  `git show --check HEAD`. Docker Compose configuration could not be resolved
  in that worktree because `LLM_PROVIDER_ENCRYPTION_KEY` was unset. No Docker
  service or service-backed valuation test ran; this was an offline report
  slice.
- The #351 matrix marks three of five as provisional only and treats
  `us-gaap:Revenues` as a candidate mapping, not a universal alias. The
  acceptance policy now explicitly separates computability from evidence:
  #351 delivers the matrix, candidate-only threshold, and abstention rules;
  #352 owns the canonical forecast composer; and the #361 replay follows #352
  using that service logic. No numerical threshold is claimed as verified.
- PR #358 had all 11 required checks pass on the exact head
  `68f305abaae1038eeeaa7b434cd45e1adadf9672`; the documentation-only
  Fundamental release gate was skipped. No review is recorded. Rerun checks
  after updating the branch.
- The GitHub dependency `#361 blocks #351` is being removed. #361 remains an
  open follow-up after #352, and must not block #351's source-and-policy
  delivery. #352 through #355 remain OPEN and unstarted; #352 still cannot
  start until #351's PR is merged and its issue is closed.

## Current sequencing decision

- #351 acceptance is complete when the source/quality matrix, the
  provisional-only history candidate, and explicit degraded/abstain behavior
  are reviewed and merged. It does not require a verified numerical history
  threshold, because the available #359 evidence is underpowered and contains
  no service-owned historical forecasts.
- The candidate rule remains latest five fiscal years with at least three
  complete comparable annual periods. It can produce at most `provisional`
  when all other gates pass. Missing, conflicting, structurally broken,
  unreviewed, or unresolved mappings produce the matrix-defined degraded or
  abstained outcome; they never become `verified` through a placeholder.
- After #352, #361 will replay predeclared history lengths in chronological
  walk-forward order with the canonical Fundamental Service composer. Each
  decision date uses only facts available then, and each label is the first
  subsequent qualifying original filing. The report must retain failed cases,
  show forecast error, coverage, independent issuers, and uncertainty, and
  leave the threshold null when evidence remains underpowered.
- This decision preserves the fixed delivery order #351 -> #352 -> #353 ->
  #354 -> #355. #355 remains an optional Search/LLM evidence path and is not a
  core valuation dependency.

## Prior checkpoint after #356 merge

- Issue: #351, first incomplete issue in the requested sequence; state OPEN.
- Branch: `codex/issue-351-valuation-evidence`.
- Current base sync: merge commit `a3fb9826` brings `origin/main` at
  `6ed0031f38b05740ae2fb47b7fbfe607963d92fa` into the existing branch without
  rewriting checkpoints `c109ae88e22937c134267c5dcd002b65074e90dc` and
  `df406030c485274146035bb2e7d5668b2badb977`.
- Pull request: #358 is OPEN as a draft and references #351 and blocker #359.
  The last verified head before this status update is
  `e720005fd8e5a51009a535b6c00a29af27665410`. GitHub run `42574487467`
  passed the required checks on that head. The draft does not claim to close
  #351.
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

## Historical checkpoint after #359 merge

- Issue #351 remains OPEN and is the first incomplete issue in the requested
  sequence. Branch: `codex/issue-351-valuation-evidence`.
- The branch now includes merge checkpoint
  `7e441d98f38939c57c13442e35e9210f149b1749`, which brings in #359's merged
  evidence from `main` at `a2956589d4f01fb0754368406c00ac6f6928e568` without
  rewriting the existing #351 commits.
- PR #358 remains OPEN as a draft. It targets `main` and references #351.
  Required checks are running on head `7e441d98f38939c57c13442e35e9210f149b1749`.
  It does not claim to close #351.
- Blocker #359 is CLOSED by PR #360 at merge commit
  `a2956589d4f01fb0754368406c00ac6f6928e568`. Its final report retains the
  100-issuer denominator, returns `underpowered`, leaves
  `supported_history_threshold` null, and requires provisional or abstained
  results. The report hash is
  `1a3995af98d3fda2166873c25f0ba981d89016ae6f6f98dc4515a077eac41b9f`; the
  capture manifest hash is
  `afad3f92f2597383d16afec2cc85850fbf5919106d3cb827a6e8112022836242`.
- The report's 0/100 revenue coverage counts only
  `RevenueFromContractWithCustomerExcludingAssessedTax`. A read-only Company
  Facts request for CIK `0001539778` returned HTTP 200 with response hash
  `6bfb258021d1976a47e06b42f3bebacbcef28d5b30fb54085a102cd839acd1c1`. The
  #359 point-in-time audit reports qualifying `us-gaap:Revenues` facts for
  decision accession `0001477932-16-007985`, where the listed concept has no
  qualifying facts. This identifies a mapping gap; it does not approve a
  universal alias or validate the history threshold.
- `FUNDAMENTAL_SEC_USER_AGENT` is set in the ignored main-checkout `.env`.
  `.env.example` on the branch and `main` contains only the
  `contact@example.com` placeholder. The real contact was not printed,
  committed, or posted to GitHub.
- New blocker #361 is OPEN and formally blocks #351. It tracks the lack of
  canonical historical service forecasts and complete out-of-sample labels,
  plus the need to review the revenue mapping before any threshold decision.
  Issues #352 through #355 remain OPEN and have not started. #355 remains
  optional and outside the core valuation dependency path.
- #351 remains WIP and unverified. The three-of-five rule remains an
  unvalidated candidate and cannot grant `verified` status. Do not start #352.

## Historical acceptance status before the revised decision

| Criterion | Evidence | Status |
| --- | --- | --- |
| Inventory each required input for both released models. | Section 24.4.4 classifies SEC facts, derived metrics, forecasts, market inputs, policy inputs, capital bridge fields, and optional forward references. | Draft matrix present; final review pending. |
| Separate computability from evidence quality and define time, freshness, and quality gates. | The matrix keeps period and availability rules, immutable evidence references, versioned freshness policy, and typed degraded, provisional, unsupported, or abstained outcomes. | Draft matrix present; final review pending. |
| Define the candidate history rule and the gate for verified eligibility. | The #359 report is underpowered and keeps `supported_history_threshold` null. The latest-five, at-least-three-complete-years rule remains a provisional candidate only. A post-#352 replay will use the canonical Fundamental Service forecast logic and chronological first-subsequent labels. | Safe provisional or abstention policy documented; validated threshold deferred. |
| Define how unresolved SEC revenue mappings affect eligibility. | The #359 report and the #361 candidate screen do not approve a canonical mapping. `us-gaap:Revenues` remains a candidate only. The matrix requires issuer, period, unit, currency, and scope review before a mapping can support verified eligibility. | Unresolved mappings remain unsupported or abstained; no universal alias. |
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

## Historical delivery gate before the revised decision

- #358 remains a draft PR. Merge checkpoint `7e441d98` is pushed. Its required
  checks were still running when this checkpoint was recorded. No review has
  been requested or recorded.
- #359 is closed, but its underpowered result does not satisfy #351's
  numerical-threshold criterion. Blocker #361 now tracks the missing
  service-owned historical forecasts, complete labels, and reviewed source
  mapping. #351 cannot be verified or merged while that criterion remains
  unmet.
- #352 cannot start until #351's acceptance criteria pass and its PR merges
  into `main`.
- No Docker Compose project was started for this documentation-only slice.

## Verification on merge checkpoint `7e441d98`

Commit `7e441d98f38939c57c13442e35e9210f149b1749` passed the merge-conflict
check and repository commit hooks. `git diff --cached --check` passed before
the commit. A read-only Company Facts GET using the local configured
User-Agent returned HTTP 200 and response SHA-256
`6bfb258021d1976a47e06b42f3bebacbcef28d5b30fb54085a102cd839acd1c1`.

No unit suite, architecture guard, Docker stack, or service-backed end-to-end
check has run on this checkpoint. The PR's required GitHub checks were still
in progress when this record was written. The threshold remains unsupported.

## Verification on prior code checkpoint

Checkpoint `e720005fd8e5a51009a535b6c00a29af27665410` records the WIP
acceptance state. These checks ran against that exact commit:

| Command or check | Result |
| --- | --- |
| `uv run --extra dev --project fundamental-service pytest fundamental-service/tests/test_sec_source.py fundamental-service/tests/test_source_acquisition.py fundamental-service/tests/test_history_sufficiency_report.py fundamental-service/tests/test_calibration.py fundamental-service/tests/test_facts.py fundamental-service/tests/test_verification.py -q` | Exit 0; 77 passed. |
| `python3 scripts/architecture_guard.py` | Exit 0; no boundary violations. |
| `docker compose --env-file .env.example config --quiet` | Exit 0. |
| `git diff origin/main...HEAD --check` | Exit 0. |
| GitHub Actions run `42574487467` on PR #358 | All 11 required checks passed. The documentation-only `fundamental-release-gate` was skipped. |

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
